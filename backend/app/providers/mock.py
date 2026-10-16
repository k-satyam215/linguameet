"""Offline providers: no keys, no network. Used for tests, demos and ₹0 UI work."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import ASRResult


class MockASR:
    name = "mock-asr"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.calls = 0

    async def transcribe(self, pcm16: bytes, sample_rate: int, language: str | None, prompt: str | None) -> ASRResult:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        secs = len(pcm16) / 2 / sample_rate
        return ASRResult(text=f"mock utterance {self.calls} ({secs:.1f}s)", language=language)


class MockTranslator:
    name = "mock-translator"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s

    async def translate_stream(
        self, text: str, source_name: str, target_name: str, glossary: list[str], context: list[str], note: str
    ) -> AsyncIterator[str]:
        words = f"[{target_name}] {text}".split(" ")
        for i, w in enumerate(words):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield w if i == 0 else " " + w

    async def aclose(self) -> None:
        return None
