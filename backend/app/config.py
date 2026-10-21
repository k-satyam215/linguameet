"""Runtime configuration. Everything is overridable via environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # "auto" -> groq when GROQ_API_KEY is set, else mock. Also: "mock" | "groq"
    provider: str = "auto"
    groq_api_key: str = ""
    groq_asr_model: str = "whisper-large-v3-turbo"
    groq_translate_model: str = "openai/gpt-oss-20b"
    groq_reasoning_effort: str = ""  # leave empty to omit the field

    # Natural-sounding translated voice (server-side TTS). "auto" -> gemini when a key is set.
    tts_provider: str = "auto"  # auto | gemini | none
    gemini_api_key: str = ""
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    tts_voices: tuple[str, ...] = ("Sulafat", "Charon", "Kore", "Puck", "Aoede", "Fenrir")
    tts_style: str = "Say in a natural, warm, conversational tone: "  # "" disables the style prefix
    tts_timeout_s: float = 10.0
    tts_concurrency: int = 3
    tts_max_chars: int = 400
    tts_per_user_per_min: int = 40

    livekit_url: str = "ws://localhost:7880"
    livekit_http_url: str = ""   # defaults to livekit_url with ws->http
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"

    # Signs the short-lived tokens that authorise the translation WebSocket.
    jwt_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    token_ttl_s: int = 6 * 3600
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    # Pipeline deadlines (seconds). Stale work is dropped, never replayed late.
    asr_timeout_s: float = 8.0
    translate_timeout_s: float = 8.0
    stale_after_s: float = 12.0
    provider_concurrency: int = 4

    # VAD / segmentation
    vad_hangover_ms: int = 450
    vad_min_speech_ms: int = 250
    vad_max_segment_ms: int = 9000
    vad_min_rms: float = 300.0

    max_participants_per_room: int = 12
    max_rooms: int = 200

    @staticmethod
    def from_env() -> "Settings":
        origins = os.environ.get("CORS_ORIGINS")
        kwargs: dict = {}
        if origins:
            kwargs["cors_origins"] = tuple(o.strip() for o in origins.split(",") if o.strip())
        if os.environ.get("JWT_SECRET"):
            kwargs["jwt_secret"] = os.environ["JWT_SECRET"]
        voices = os.environ.get("TTS_VOICES")
        if voices:
            kwargs["tts_voices"] = tuple(v.strip() for v in voices.split(",") if v.strip())
        style = os.environ.get("TTS_STYLE")
        if style is not None:
            kwargs["tts_style"] = style
        return Settings(
            tts_provider=os.environ.get("TTS_PROVIDER", "auto").lower(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_tts_model=os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"),
            tts_timeout_s=_f("TTS_TIMEOUT_S", 10.0),
            tts_concurrency=_i("TTS_CONCURRENCY", 3),
            tts_max_chars=_i("TTS_MAX_CHARS", 400),
            tts_per_user_per_min=_i("TTS_PER_USER_PER_MIN", 40),
            provider=os.environ.get("PROVIDER", "auto").lower(),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            groq_asr_model=os.environ.get("GROQ_ASR_MODEL", "whisper-large-v3-turbo"),
            groq_translate_model=os.environ.get("GROQ_TRANSLATE_MODEL", "openai/gpt-oss-20b"),
            groq_reasoning_effort=os.environ.get("GROQ_REASONING_EFFORT", ""),
            livekit_url=os.environ.get("LIVEKIT_URL", "ws://localhost:7880"),
            livekit_http_url=os.environ.get("LIVEKIT_HTTP_URL", ""),
            livekit_api_key=os.environ.get("LIVEKIT_API_KEY", "devkey"),
            livekit_api_secret=os.environ.get("LIVEKIT_API_SECRET", "secret"),
            asr_timeout_s=_f("ASR_TIMEOUT_S", 8.0),
            translate_timeout_s=_f("TRANSLATE_TIMEOUT_S", 8.0),
            stale_after_s=_f("STALE_AFTER_S", 12.0),
            provider_concurrency=_i("PROVIDER_CONCURRENCY", 4),
            vad_hangover_ms=_i("VAD_HANGOVER_MS", 450),
            vad_min_speech_ms=_i("VAD_MIN_SPEECH_MS", 250),
            vad_max_segment_ms=_i("VAD_MAX_SEGMENT_MS", 9000),
            vad_min_rms=_f("VAD_MIN_RMS", 300.0),
            max_participants_per_room=_i("MAX_PARTICIPANTS_PER_ROOM", 12),
            max_rooms=_i("MAX_ROOMS", 200),
            **kwargs,
        )
