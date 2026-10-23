"""LanguageRegistry: one place that says what each language can do.

Capabilities are *declared per language* and are provider-independent defaults.
`tts` means "browser speechSynthesis may have a voice"; actual voice availability
depends on the listener's OS/browser, so the client re-checks it and falls back
to captions-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Language:
    code: str            # internal code, e.g. "hi", "en", "hi-en"
    name: str            # display name
    base: str            # ISO-639-1 used for ASR / translation, e.g. "hi"
    bcp47: str           # used for speechSynthesis, e.g. "hi-IN"
    asr: bool = True
    translate: bool = True
    tts: bool = True
    # Optional prompt that biases ASR (used for Hinglish: roman-script output).
    asr_prompt: str = ""
    # Extra instruction injected into the translation prompt.
    note: str = ""


HINGLISH_ASR_PROMPT = (
    "Hinglish meeting audio with Hindi-English code-switching. Preserve English technical terms and names. "
    "Write Hindi words in Roman script and transcribe only words that are audible."
)

_LANGS: list[Language] = [
    Language("en", "English", "en", "en-US"),
    Language("hi", "Hindi", "hi", "hi-IN"),
    Language(
        "hi-en", "Hinglish", "hi", "hi-IN",
        asr_prompt=HINGLISH_ASR_PROMPT,
        note=(
            "The speaker mixes Hindi and English (Hinglish). Treat it as one language. "
            "Keep technical English terms, product names and numbers exactly as spoken."
        ),
    ),
    Language("bn", "Bengali", "bn", "bn-IN"),
    Language("ta", "Tamil", "ta", "ta-IN"),
    Language("te", "Telugu", "te", "te-IN"),
    Language("mr", "Marathi", "mr", "mr-IN"),
    Language("es", "Spanish", "es", "es-ES"),
    Language("fr", "French", "fr", "fr-FR"),
    Language("de", "German", "de", "de-DE"),
    Language("ja", "Japanese", "ja", "ja-JP"),
    Language("pt", "Portuguese", "pt", "pt-BR"),
]


class LanguageRegistry:
    def __init__(self, languages: list[Language] | None = None) -> None:
        self._by_code = {l.code: l for l in (languages or _LANGS)}
        self._by_name = {l.name.lower(): l for l in self._by_code.values() if l.code != "hi-en"}

    def get(self, code: str) -> Language | None:
        return self._by_code.get(code)

    def require(self, code: str) -> Language:
        lang = self.get(code)
        if lang is None:
            raise KeyError(f"unsupported language: {code}")
        return lang

    def from_name(self, name: str) -> Language | None:
        """Map provider language names (e.g. Whisper's 'english') to a Language."""
        return self._by_name.get((name or "").strip().lower())

    def can_listen(self, code: str) -> bool:
        l = self.get(code)
        return bool(l and l.translate)

    def can_speak(self, code: str) -> bool:
        l = self.get(code)
        return bool(l and l.asr)

    def same_language(self, a: str, b: str) -> bool:
        """Hindi and Hinglish are mutually intelligible for our purposes."""
        la, lb = self.get(a), self.get(b)
        return bool(la and lb and la.base == lb.base)

    def public(self) -> list[dict]:
        return [asdict(l) for l in self._by_code.values()]


DEFAULT_REGISTRY = LanguageRegistry()
