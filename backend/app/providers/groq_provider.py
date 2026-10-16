"""Groq adapters: Whisper ASR + streaming chat translation over plain HTTPS.

Model names are configurable because provider catalogues change. Nothing here has
been benchmarked for Hindi/Hinglish quality or latency yet -- run `scripts/bench.py`
with your own recordings before trusting it.
"""
from __future__ import annotations

import io
import json
import wave
from typing import AsyncIterator

import httpx

from .base import ASRResult, ProviderError, RateLimited

BASE = "https://api.groq.com/openai/v1"


def pcm_to_wav(pcm16: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


class GroqASR:
    name = "groq-whisper"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def transcribe(self, pcm16: bytes, sample_rate: int, language: str | None, prompt: str | None) -> ASRResult:
        data = {"model": self._model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        files = {"file": ("audio.wav", pcm_to_wav(pcm16, sample_rate), "audio/wav")}
        try:
            r = await self._client.post(
                f"{BASE}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                data=data,
                files=files,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"asr network error: {e}") from e
        if r.status_code == 429:
            raise RateLimited(_retry_after(r))
        if r.status_code >= 400:
            raise ProviderError(f"asr http {r.status_code}: {r.text[:200]}")
        body = r.json()
        return ASRResult(text=(body.get("text") or "").strip(), language=body.get("language"))


class GroqTranslator:
    name = "groq-chat"

    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key = api_key
        self._model = model
        self._effort = reasoning_effort
        self._client = client or httpx.AsyncClient(timeout=20.0)

    @staticmethod
    def build_messages(
        text: str, source_name: str, target_name: str, glossary: list[str], context: list[str], note: str
    ) -> list[dict]:
        rules = [
            f"You are a live interpreter in a video meeting. Translate from {source_name} to {target_name}.",
            "Output ONLY the translation: no quotes, no notes, no explanations.",
            "Be faithful and natural for spoken conversation. Keep names, numbers, code identifiers and product names intact.",
            "If the input is a fragment, translate the fragment; never invent missing words.",
        ]
        if note:
            rules.append(note)
        if glossary:
            rules.append("Glossary (keep or translate consistently): " + "; ".join(glossary[:50]))
        if context:
            rules.append("Earlier sentences from this speaker (context only, do not translate): " + " | ".join(context[-3:]))
        return [
            {"role": "system", "content": "\n".join(rules)},
            {"role": "user", "content": text},
        ]

    async def translate_stream(
        self, text: str, source_name: str, target_name: str, glossary: list[str], context: list[str], note: str
    ) -> AsyncIterator[str]:
        payload: dict = {
            "model": self._model,
            "messages": self.build_messages(text, source_name, target_name, glossary, context, note),
            "temperature": 0.1,
            "max_tokens": 400,
            "stream": True,
        }
        if self._effort:
            payload["reasoning_effort"] = self._effort
        try:
            async with self._client.stream(
                "POST",
                f"{BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
            ) as r:
                if r.status_code == 429:
                    raise RateLimited(_retry_after(r))
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "ignore")[:200]
                    raise ProviderError(f"translate http {r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise ProviderError(f"translate network error: {e}") from e

    async def aclose(self) -> None:
        await self._client.aclose()
