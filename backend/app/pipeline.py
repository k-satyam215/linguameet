"""Streaming speech-translation pipeline for ONE utterance.

    segment --ASR--> original caption (sent immediately)
                +--> per target language: streaming translation -> partial/final captions

Design rules (latency + honesty):
  * The original-language caption goes out the moment ASR returns, so people see
    *something* long before the translation finishes.
  * Translation streams partials; the client speaks completed sentences early.
  * Each distinct target language is translated ONCE and fanned out to all
    listeners of that language. Languages nobody selected are never processed.
  * Every stage has a deadline. Stale work is dropped with an explicit status event.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .config import Settings
from .languages import LanguageRegistry
from .latency import Metrics
from .providers import ASR, ProviderError, RateLimited, Translator
from .vad import SAMPLE_RATE, Segment

# audience: "*all" | "*speaker" | "lang:<code>"
Emit = Callable[[str, dict], Awaitable[None]]

# Whisper tends to hallucinate these on near-silence.
_HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching", "you", "bye", "bye.",
    "subtitles by the amara.org community", ".",
}
_PARTIAL_EVERY_S = 0.05


@dataclass
class Utterance:
    speaker_id: str
    speaker_name: str
    source_lang: str            # registry code, or "auto"
    segment: Segment
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def looks_like_hallucination(text: str) -> bool:
    t = re.sub(r"\s+", " ", text.strip().lower())
    t = t.strip(" .!?,")
    if len(t) < 2:
        return True
    return t in _HALLUCINATIONS or t + "." in _HALLUCINATIONS


class TranslationPipeline:
    def __init__(
        self,
        asr: ASR,
        translator: Translator,
        registry: LanguageRegistry,
        metrics: Metrics,
        settings: Settings,
    ) -> None:
        self.asr = asr
        self.translator = translator
        self.registry = registry
        self.metrics = metrics
        self.settings = settings
        self._sem = asyncio.Semaphore(max(1, settings.provider_concurrency))

    async def process(
        self,
        utt: Utterance,
        targets: set[str],
        glossary: list[str],
        history: list[str],
        emit: Emit,
        clock: Callable[[], float] = time.monotonic,
    ) -> str | None:
        """Run the pipeline. Returns the recognised source text (or None if nothing)."""
        seg = utt.segment
        t_seg = seg.detected_at
        src = self.registry.get(utt.source_lang)
        asr_lang = src.base if src else None
        asr_prompt = src.asr_prompt if src else None
        if glossary:
            extra = ", ".join(glossary[:30])
            asr_prompt = f"{asr_prompt + ' ' if asr_prompt else ''}Terms: {extra}."

        # ---- ASR ---------------------------------------------------------
        try:
            async with self._sem:
                res = await asyncio.wait_for(
                    self.asr.transcribe(seg.pcm, SAMPLE_RATE, asr_lang, asr_prompt),
                    timeout=self.settings.asr_timeout_s,
                )
        except RateLimited:
            self.metrics.incr("asr_rate_limited")
            await emit("*speaker", _status(utt, "rate_limited", "Speech recognition quota reached; this sentence was skipped."))
            return None
        except (ProviderError, asyncio.TimeoutError) as e:
            self.metrics.incr("asr_failed")
            await emit("*speaker", _status(utt, "asr_failed", f"Speech recognition failed: {type(e).__name__}"))
            return None

        text = res.text.strip()
        if not text or looks_like_hallucination(text):
            self.metrics.incr("asr_empty")
            return None

        t_asr = clock()
        asr_ms = (t_asr - t_seg) * 1000
        self.metrics.record("asr_ms", asr_ms)

        detected = self.registry.from_name(res.language or "") if res.language else None
        if utt.source_lang == "auto":
            source = detected.code if detected else (res.language or "en")
        else:
            source = utt.source_lang

        # ---- original caption: immediately -------------------------------
        since_end_ms = seg.hangover_ms + asr_ms
        await emit("*all", {
            "type": "caption", "id": utt.id, "kind": "original", "lang": source,
            "speaker": utt.speaker_id, "speakerName": utt.speaker_name,
            "text": text, "final": True,
            "timings": {"asr_ms": round(asr_ms), "since_speech_end_ms": round(since_end_ms)},
        })
        self.metrics.record("original_caption_since_speech_end_ms", since_end_ms)

        # ---- translations, one per distinct target language --------------
        todo = [t for t in sorted(targets) if not self.registry.same_language(t, source)]
        if todo:
            if clock() - t_seg > self.settings.stale_after_s:
                self.metrics.incr("stale_dropped")
                await emit("*speaker", _status(utt, "stale", "Translation dropped: pipeline was too far behind."))
            else:
                await asyncio.gather(*(
                    self._translate_one(utt, source, tgt, text, glossary, history, emit, asr_ms, clock)
                    for tgt in todo
                ))
        return text

    async def _translate_one(
        self, utt: Utterance, source: str, target: str, text: str,
        glossary: list[str], history: list[str], emit: Emit, asr_ms: float,
        clock: Callable[[], float],
    ) -> None:
        reg = self.registry
        src_l, tgt_l = reg.get(source), reg.require(target)
        src_name = src_l.name if src_l else source
        note = " ".join(x for x in ((src_l.note if src_l else ""), tgt_l.note) if x)
        t_seg = utt.segment.detected_at
        t_start = clock()
        acc = ""
        first_token_ms: float | None = None
        last_emit = 0.0
        audience = f"lang:{target}"

        async def _run() -> None:
            nonlocal acc, first_token_ms, last_emit
            async with self._sem:
                async for delta in self.translator.translate_stream(
                    text, src_name, tgt_l.name, glossary, history, note
                ):
                    acc += delta
                    now = clock()
                    if first_token_ms is None:
                        first_token_ms = (now - t_seg) * 1000
                        self.metrics.record("translate_first_token_ms", (now - t_start) * 1000)
                    if now - last_emit >= _PARTIAL_EVERY_S:
                        last_emit = now
                        await emit(audience, self._cap(utt, target, acc, False, None))

        try:
            await asyncio.wait_for(_run(), timeout=self.settings.translate_timeout_s)
        except RateLimited:
            self.metrics.incr("translate_rate_limited")
            await emit("*speaker", _status(utt, "rate_limited", f"Translation to {tgt_l.name} skipped (provider quota)."))
            return
        except (ProviderError, asyncio.TimeoutError) as e:
            self.metrics.incr("translate_failed")
            await emit("*speaker", _status(utt, "translate_failed", f"Translation to {tgt_l.name} failed: {type(e).__name__}"))
            return

        final = acc.strip()
        if not final:
            return
        now = clock()
        total_ms = (now - t_start) * 1000
        e2e_ms = utt.segment.hangover_ms + (now - t_seg) * 1000
        self.metrics.record("translate_total_ms", total_ms)
        self.metrics.record("e2e_final_ms", e2e_ms)
        if first_token_ms is not None:
            self.metrics.record("e2e_first_token_ms", utt.segment.hangover_ms + first_token_ms)
        timings = {
            "asr_ms": round(asr_ms),
            "first_token_ms": round(utt.segment.hangover_ms + (first_token_ms or 0)),
            "translate_ms": round(total_ms),
            "e2e_ms": round(e2e_ms),
        }
        await emit(audience, self._cap(utt, target, final, True, timings))

    @staticmethod
    def _cap(utt: Utterance, lang: str, text: str, final: bool, timings: dict | None) -> dict:
        ev = {
            "type": "caption", "id": utt.id, "kind": "translation", "lang": lang,
            "speaker": utt.speaker_id, "speakerName": utt.speaker_name,
            "text": text, "final": final,
        }
        if timings is not None:
            ev["timings"] = timings
        return ev


def _status(utt: Utterance, code: str, message: str) -> dict:
    return {"type": "status", "code": code, "message": message, "id": utt.id}
