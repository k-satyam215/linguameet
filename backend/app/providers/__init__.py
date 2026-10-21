from __future__ import annotations

from ..config import Settings
from .base import ASR, TTS, ASRResult, ProviderError, RateLimited, Translator, TtsAudio
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


def build_tts(settings: Settings) -> TTS | None:
    """Natural-voice provider, or None (the browser then falls back to its own voices)."""
    choice = settings.tts_provider
    if choice == "auto":
        choice = "gemini" if settings.gemini_api_key else "none"
    if choice == "none":
        return None
    if choice == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("TTS_PROVIDER=gemini requires GEMINI_API_KEY")
        from .gemini_tts import GeminiTTS

        return GeminiTTS(settings.gemini_api_key, settings.gemini_tts_model, settings.tts_style, timeout=settings.tts_timeout_s)
    raise RuntimeError(f"unknown tts provider: {settings.tts_provider}")


__all__ = ["ASR", "TTS", "ASRResult", "TtsAudio", "Translator", "ProviderError", "RateLimited", "build_providers", "build_tts"]
