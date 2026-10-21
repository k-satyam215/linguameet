import asyncio
import base64
import json
import struct

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.latency import Metrics
from app.main import create_app
from app.providers.base import ProviderError, RateLimited, TtsAudio
from app.providers.gemini_tts import GeminiTTS
from app.tts_service import TtsBusy, TtsService, TtsTooLong

SETTINGS = Settings(provider="mock", jwt_secret="tts-test-secret-tts-test-secret-12345")


class FakeTTS:
    name = "fake-tts"

    def __init__(self, delay: float = 0.0, error: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.delay = delay
        self.error = error

    async def synthesize(self, text, voice):
        self.calls.append((text, voice))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return TtsAudio(pcm=struct.pack("<8h", *range(8)), sample_rate=24000)

    async def aclose(self):
        pass


def client(tts):
    return TestClient(create_app(SETTINGS, tts=tts))


def token(c, name="A", room="tts-room"):
    return c.post("/api/join", json={"room": room, "name": name, "speak": "en", "listen": "hi"}).json()["ws_token"]


def post(c, tok, text="Hello there.", speaker="u_x"):
    return c.post("/api/tts", json={"text": text, "speaker": speaker}, headers={"Authorization": f"Bearer {tok}"})


# ---- endpoint -----------------------------------------------------------------------------

def test_tts_disabled_by_default_and_health_says_so():
    with TestClient(create_app(SETTINGS)) as c:
        assert c.get("/api/health").json()["tts"] == "none"
        assert post(c, token(c)).status_code == 404


def test_tts_requires_valid_session():
    with client(FakeTTS()) as c:
        assert c.post("/api/tts", json={"text": "hi"}).status_code == 401
        assert c.post("/api/tts", json={"text": "hi"}, headers={"Authorization": "Bearer junk"}).status_code == 401


def test_tts_returns_wav_and_ready_event_announces_it():
    fake = FakeTTS()
    with client(fake) as c:
        assert c.get("/api/health").json()["tts"] == "fake-tts"
        tok = token(c)
        r = post(c, tok)
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"
        assert struct.unpack("<I", r.content[24:28])[0] == 24000
        with c.websocket_connect(f"/ws/translate?token={tok}") as ws:
            assert ws.receive_json()["tts"] == "fake-tts"


def test_tts_voice_is_stable_per_speaker_and_cached():
    fake = FakeTTS()
    svc = TtsService(fake, SETTINGS, Metrics())
    with client(fake) as c:
        tok = token(c)
        post(c, tok, "Same line.", "u_alice")
        post(c, tok, "Same line.", "u_alice")          # cache hit: no second provider call
        assert len(fake.calls) == 1
        assert fake.calls[0] == ("Same line.", svc.voice_for("u_alice"))
        assert fake.calls[0][0] == "Same line."        # style prefix is added by the adapter, not the service


def test_tts_rejects_long_text_and_maps_failures():
    with client(FakeTTS()) as c:
        assert post(c, token(c), "x" * 401).status_code == 413
    with client(FakeTTS(error=ProviderError("boom"))) as c:
        assert post(c, token(c)).status_code == 502


def test_tts_rate_limit_becomes_429_and_cooldown_stops_hammering():
    fake = FakeTTS(error=RateLimited(5))
    with client(fake) as c:
        tok = token(c)
        r = post(c, tok, "one")
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 5
        assert post(c, tok, "two").status_code == 429
    assert len(fake.calls) == 1            # second request never reached the provider


# ---- service ------------------------------------------------------------------------------

async def test_same_sentence_for_many_listeners_is_one_provider_call():
    fake = FakeTTS(delay=0.05)
    svc = TtsService(fake, SETTINGS, Metrics())
    out = await asyncio.gather(*(svc.speak(f"u{i}", "Shared sentence.", "u_speaker") for i in range(5)))
    assert len(fake.calls) == 1 and all(o == out[0] for o in out)


async def test_per_user_limit_and_length_guard():
    s = Settings(provider="mock", tts_per_user_per_min=2, tts_max_chars=10)
    svc = TtsService(FakeTTS(), s, Metrics())
    await svc.speak("u", "a", "sp")
    await svc.speak("u", "b", "sp")
    with pytest.raises(TtsBusy):
        await svc.speak("u", "c", "sp")
    with pytest.raises(TtsTooLong):
        await svc.speak("other", "this is far too long", "sp")
    await svc.speak("u", "a", "sp")        # cached text is still served when the user is over the limit


async def test_failed_call_is_not_cached():
    fake = FakeTTS(error=ProviderError("x"))
    svc = TtsService(fake, SETTINGS, Metrics())
    with pytest.raises(ProviderError):
        await svc.speak("u", "retry me", "sp")
    fake.error = None
    assert (await svc.speak("u", "retry me", "sp"))[:4] == b"RIFF"
    assert len(fake.calls) == 2


def test_voice_assignment_is_deterministic_and_spreads():
    svc = TtsService(FakeTTS(), SETTINGS, Metrics())
    ids = [f"u_{i:04x}" for i in range(60)]
    assert [svc.voice_for(i) for i in ids] == [svc.voice_for(i) for i in ids]
    assert len({svc.voice_for(i) for i in ids}) >= 4


# ---- Gemini adapter against a fake HTTP transport -----------------------------------------

def gemini(handler, style="Say warmly: "):
    return GeminiTTS("test-key", "tts-model", style, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_gemini_request_shape_and_pcm_decode():
    pcm = struct.pack("<4h", 1, -2, 3, -4)
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-goog-api-key"], json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=16000", "data": base64.b64encode(pcm).decode()}}]}}]})

    audio = await gemini(handler).synthesize("नमस्ते", "Kore")
    assert audio.pcm == pcm and audio.sample_rate == 16000
    assert seen["url"].endswith("/models/tts-model:generateContent") and seen["key"] == "test-key"
    assert "key=" not in seen["url"]                      # the key never goes in the URL
    body = seen["body"]
    assert body["contents"][0]["parts"][0]["text"] == "Say warmly: नमस्ते"
    assert body["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"


async def test_gemini_errors_are_classified():
    with pytest.raises(RateLimited) as e:
        await gemini(lambda r: httpx.Response(429, headers={"retry-after": "7"})).synthesize("hi", "Kore")
    assert e.value.retry_after == 7
    with pytest.raises(ProviderError):
        await gemini(lambda r: httpx.Response(400, text="bad")).synthesize("hi", "Kore")
    with pytest.raises(ProviderError):
        await gemini(lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "I will not"}]}}]})).synthesize("hi", "Kore")

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError):
        await gemini(boom).synthesize("hi", "Kore")


async def test_gemini_retries_one_transient_5xx():
    n = {"c": 0}
    pcm = base64.b64encode(b"\x01\x00" * 4).decode()

    def handler(req):
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": pcm}}]}}]})

    audio = await gemini(handler).synthesize("hi", "Kore")
    assert n["c"] == 2 and audio.sample_rate == 24000


async def test_gemini_38_uses_current_tts_payload_and_pcm_format():
    pcm = struct.pack("<4h", 1, -2, 3, -4)
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})

    audio = await GeminiTTS("test-key", "gemini-3.8-flash-tts", "warm and conversational",
                            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))).synthesize("नमस्ते", "Kore")
    body = seen["body"]
    assert audio.pcm == pcm and audio.sample_rate == 24000
    assert body["contents"][0]["role"] == "user"
    assert body["contents"][0]["parts"][0] == {
        "text": "नमस्ते", "speech_metadata": {"style": "warm and conversational"}
    }
    assert body["generationConfig"]["responseFormat"]["audio"] == {
        "mimeType": "AUDIO_L16", "sampleRate": 24000
    }
    assert body["generationConfig"]["speechConfig"]["voiceConfig"]["voice"] == "Kore"
