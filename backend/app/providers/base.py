"""Provider interfaces. Every AI vendor sits behind these so it can be swapped."""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


class ProviderError(Exception):
    """Generic provider failure (network, 5xx, bad payload)."""


class RateLimited(ProviderError):
    """Provider quota hit. We respect it: no key rotation, no hammering."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


@dataclass
class ASRResult:
    text: str
    language: str | None = None   # ISO-639-1 code when the provider detects it


class ASR(Protocol):
    name: str

    async def transcribe(
        self, pcm16: bytes, sample_rate: int, language: str | None, prompt: str | None
    ) -> ASRResult: ...


class Translator(Protocol):
    name: str

    def translate_stream(
        self,
        text: str,
        source_name: str,
        target_name: str,
        glossary: list[str],
        context: list[str],
        note: str,
    ) -> AsyncIterator[str]:
        """Yield text deltas of the translation as they are produced."""
        ...

    async def aclose(self) -> None: ...


@dataclass
class TtsAudio:
    pcm: bytes          # 16-bit little-endian mono PCM
    sample_rate: int


class TTS(Protocol):
    name: str

    async def synthesize(self, text: str, voice: str) -> TtsAudio: ...

    async def aclose(self) -> None: ...
