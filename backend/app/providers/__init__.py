from __future__ import annotations

from ..config import Settings
from .base import ASR, ASRResult, ProviderError, RateLimited, Translator
from .mock import MockASR, MockTranslator


def build_providers(settings: Settings) -> tuple[ASR, Translator, str]:
    """Return (asr, translator, provider_name) for the configured provider."""
    choice = settings.provider
    if choice == "auto":
        choice = "groq" if settings.groq_api_key else "mock"
    if choice == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("PROVIDER=groq requires GROQ_API_KEY")
        from .groq_provider import GroqASR, GroqTranslator

        return (
            GroqASR(settings.groq_api_key, settings.groq_asr_model),
            GroqTranslator(settings.groq_api_key, settings.groq_translate_model, settings.groq_reasoning_effort),
            "groq",
        )
    if choice == "mock":
        return MockASR(), MockTranslator(), "mock"
    raise RuntimeError(f"unknown provider: {settings.provider}")


__all__ = ["ASR", "ASRResult", "Translator", "ProviderError", "RateLimited", "build_providers"]
