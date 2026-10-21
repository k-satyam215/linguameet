"""Gemini text-to-speech adapter (natural, expressive voices) over plain HTTPS.

The model name is configurable because preview model names change. Nothing here has been
benchmarked for latency or Hindi/Hinglish quality yet -- measure on your own network.
"""
from __future__ import annotations

import asyncio
import base64
import re

import httpx

from .base import ProviderError, RateLimited, TtsAudio

BASE = "https://generativelanguage.googleapis.com/v1beta"
_RATE_RE = re.compile(r"rate=(\d+)")


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


class GeminiTTS:
    name = "gemini-tts"

    def __init__(self, api_key: str, model: str, style: str = "", client: httpx.AsyncClient | None = None,
                 timeout: float = 10.0) -> None:
        self._key = api_key
        self._model = model
        self._style = style
        self._client = client or httpx.AsyncClient(timeout=timeout)

    def build_payload(self, text: str, voice: str) -> dict:
        if self._model.startswith("gemini-3.8-"):
            part = {"text": text}
            if self._style:
                part["speech_metadata"] = {"style": self._style}
            return {
                "contents": [{"role": "user", "parts": [part]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "responseFormat": {"audio": {"mimeType": "AUDIO_L16", "sampleRate": 24000}},
                    "speechConfig": {"voiceConfig": {"voice": voice}},
                },
            }
        return {
            "contents": [{"parts": [{"text": f"{self._style}{text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }

    async def synthesize(self, text: str, voice: str) -> TtsAudio:
        payload = self.build_payload(text, voice)
        resp = None
        for attempt in range(2):   # the preview TTS models occasionally return a transient 5xx
            try:
                resp = await self._client.post(
                    f"{BASE}/models/{self._model}:generateContent",
                    headers={"x-goog-api-key": self._key},
                    json=payload,
                )
            except httpx.HTTPError as e:
                raise ProviderError(f"tts network error: {e}") from e
            if resp.status_code in (500, 503) and attempt == 0:
                await asyncio.sleep(0.3)
                continue
            break
        assert resp is not None
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        if resp.status_code >= 400:
            raise ProviderError(f"tts http {resp.status_code}: {resp.text[:200]}")
        try:
            part = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
            m = _RATE_RE.search(part.get("mimeType", ""))
            rate = int(m.group(1)) if m else 24000
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError("tts returned no audio") from e
        if not pcm:
            raise ProviderError("tts returned empty audio")
        return TtsAudio(pcm=pcm, sample_rate=rate)

    async def aclose(self) -> None:
        await self._client.aclose()
