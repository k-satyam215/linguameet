"""Groq adapters against a fake HTTP transport -- no network, no key."""
import httpx
import pytest

from app.providers.base import ProviderError, RateLimited
from app.providers.groq_provider import GroqASR, GroqTranslator, pcm_to_wav


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_wav_header_is_valid():
    wav = pcm_to_wav(b"\x00\x00" * 160, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


async def test_asr_parses_text_and_language_and_sends_hints():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = req.content
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"text": " namaste ", "language": "hindi"})

    asr = GroqASR("KEY", "whisper-x", client_for(handler))
    r = await asr.transcribe(b"\x00\x00" * 160, 16000, "hi", "Kal deployment hai")
    assert r.text == "namaste" and r.language == "hindi"
    assert seen["auth"] == "Bearer KEY"
    assert b"whisper-x" in seen["body"] and b"Kal deployment hai" in seen["body"]


async def test_asr_429_raises_rate_limited_with_retry_after():
    asr = GroqASR("K", "m", client_for(lambda r: httpx.Response(429, headers={"retry-after": "3"})))
    with pytest.raises(RateLimited) as e:
        await asr.transcribe(b"\x00\x00", 16000, None, None)
    assert e.value.retry_after == 3.0


async def test_asr_server_error_raises_provider_error():
    asr = GroqASR("K", "m", client_for(lambda r: httpx.Response(500, text="oops")))
    with pytest.raises(ProviderError):
        await asr.transcribe(b"\x00\x00", 16000, None, None)


SSE = (
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
    'data: {"choices":[{"delta":{"reasoning":"hidden"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    "data: [DONE]\n\n"
)


async def test_translator_streams_only_content_deltas():
    captured = {}

    def handler(req: httpx.Request):
        import json
        captured["payload"] = json.loads(req.content)
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    t = GroqTranslator("K", "chat-x", "low", client_for(handler))
    out = [d async for d in t.translate_stream("namaste", "Hindi", "English", ["RepoMind"], ["prev"], "NOTE")]
    assert out == ["Hel", "lo"]
    p = captured["payload"]
    assert p["stream"] is True and p["reasoning_effort"] == "low" and p["model"] == "chat-x"
    system = p["messages"][0]["content"]
    assert "Hindi to English" in system and "RepoMind" in system and "prev" in system and "NOTE" in system


async def test_translator_429():
    t = GroqTranslator("K", "m", "", client_for(lambda r: httpx.Response(429)))
    with pytest.raises(RateLimited):
        async for _ in t.translate_stream("x", "Hindi", "English", [], [], ""):
            pass
