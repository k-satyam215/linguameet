"""Server-side voice for translated sentences: stable voice per speaker, cache, single-flight,
concurrency cap, per-user limit, and a cool-down when the provider says 429 (we respect it)."""
from __future__ import annotations

import asyncio
import io
import time
import wave
import zlib
from collections import OrderedDict, defaultdict, deque

from .config import Settings
from .latency import Metrics
from .providers.base import TTS, ProviderError, RateLimited, TtsAudio


class TtsBusy(Exception):
    """Voice is temporarily unavailable (rate limit / cool-down). Clients fall back to browser voices."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("tts busy")
        self.retry_after = retry_after


class TtsTooLong(Exception):
    pass


def pcm_to_wav(audio: TtsAudio) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes(audio.pcm)
    return buf.getvalue()


class TtsService:
    def __init__(self, tts: TTS, settings: Settings, metrics: Metrics, cache_size: int = 256) -> None:
        self.tts = tts
        self.s = settings
        self.metrics = metrics
        self._sem = asyncio.Semaphore(max(1, settings.tts_concurrency))
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._cache_size = cache_size
        self._inflight: dict[tuple[str, str], asyncio.Future[bytes]] = {}
        self._cooldown_until = 0.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def voice_for(self, speaker: str) -> str:
        voices = self.s.tts_voices or ("Kore",)
        return voices[zlib.crc32(speaker.encode()) % len(voices)]

    def _check_user(self, user: str) -> None:
        now = time.monotonic()
        q = self._hits[user]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.s.tts_per_user_per_min:
            raise TtsBusy(60 - (now - q[0]))
        q.append(now)

    async def speak(self, user: str, text: str, speaker: str) -> bytes:
        text = text.strip()
        if not text:
            raise ProviderError("empty text")
        if len(text) > self.s.tts_max_chars:
            raise TtsTooLong()
        voice = self.voice_for(speaker or user)
        key = (voice, text)
        if key in self._cache:                      # cache hits are free: no limit, no provider call
            self._cache.move_to_end(key)
            self.metrics.incr("tts_cache_hit")
            return self._cache[key]
        self._check_user(user)
        now = time.monotonic()
        if now < self._cooldown_until:
            raise TtsBusy(self._cooldown_until - now)
        if key in self._inflight:                   # same sentence for several listeners: one provider call
            return await asyncio.shield(self._inflight[key])
        fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            wav = await self._synthesize(text, voice)
            self._cache[key] = wav
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            fut.set_result(wav)
            return wav
        except asyncio.CancelledError:
            fut.cancel()
            raise
        except Exception as e:
            fut.set_exception(e)
            fut.exception()                         # mark retrieved: no "never retrieved" warning
            raise
        finally:
            self._inflight.pop(key, None)

    async def _synthesize(self, text: str, voice: str) -> bytes:
        t0 = time.monotonic()
        try:
            async with self._sem:
                audio = await asyncio.wait_for(self.tts.synthesize(text, voice), self.s.tts_timeout_s + 2)
        except RateLimited as e:
            wait = e.retry_after or 20.0
            self._cooldown_until = time.monotonic() + wait
            self.metrics.incr("tts_rate_limited")
            raise TtsBusy(wait) from e
        except (ProviderError, asyncio.TimeoutError):
            self.metrics.incr("tts_error")
            raise
        self.metrics.record("tts_ms", (time.monotonic() - t0) * 1000)
        self.metrics.incr("tts_ok")
        return pcm_to_wav(audio)

    async def aclose(self) -> None:
        await self.tts.aclose()
