import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app

from .helpers import chunks, utterance_audio

SETTINGS = Settings(provider="mock", jwt_secret="test-secret-test-secret-test-secret-123", livekit_api_key="k",
                    livekit_api_secret="livekit-test-secret-livekit-test-secret",
                    vad_min_rms=300.0)


@pytest.fixture
def client():
    app = create_app(SETTINGS)
    with TestClient(app) as c:
        yield c


def join(client, room="demo-room", name="Rahul", speak="hi", listen="en"):
    r = client.post("/api/join", json={"room": room, "name": name, "speak": speak, "listen": listen})
    assert r.status_code == 200, r.text
    return r.json()


def drain_until(ws, pred, limit=60):
    for _ in range(limit):
        ev = ws.receive_json()
        if pred(ev):
            return ev
    raise AssertionError("expected event never arrived")


def test_health_and_languages(client):
    assert client.get("/api/health").json()["provider"] == "mock"
    codes = {l["code"] for l in client.get("/api/languages").json()["languages"]}
    assert {"en", "hi", "hi-en"} <= codes


def test_join_returns_valid_livekit_token(client):
    j = join(client)
    claims = jwt.decode(j["livekit_token"], "livekit-test-secret-livekit-test-secret", algorithms=["HS256"])
    assert claims["iss"] == "k" and claims["video"]["room"] == "demo-room" and claims["video"]["roomJoin"]
    assert claims["sub"] == j["identity"]


@pytest.mark.parametrize("room", ["", "ab", "bad room!", "x" * 41, "../etc"])
def test_bad_room_codes_rejected(client, room):
    r = client.post("/api/join", json={"room": room, "name": "A", "speak": "en", "listen": "en"})
    assert r.status_code == 400


def test_unsupported_language_rejected(client):
    r = client.post("/api/join", json={"room": "demo-room", "name": "A", "speak": "xx", "listen": "en"})
    assert r.status_code == 400
    r = client.post("/api/join", json={"room": "demo-room", "name": "A", "speak": "en", "listen": "xx"})
    assert r.status_code == 400


def test_ws_rejects_missing_or_forged_token(client):
    for tok in ("", "garbage", jwt.encode({"aud": "translate-ws", "room": "x", "sub": "u", "name": "n",
                                           "speak": "en", "listen": "en"}, "wrong-secret-wrong-secret-wrong-secret-1", algorithm="HS256")):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/translate?token={tok}"):
                pass


def test_two_participants_translate_end_to_end(client):
    a = join(client, name="Rahul", speak="hi", listen="hi")
    b = join(client, name="Emma", speak="en", listen="en")
    with client.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa, \
         client.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
        assert wa.receive_json()["type"] == "ready"
        assert wb.receive_json()["type"] == "ready"
        drain_until(wb, lambda e: e["type"] == "roster" and len(e["participants"]) == 2)

        for c in chunks(utterance_audio(700, 800)):
            wa.send_bytes(c)

        orig = drain_until(wb, lambda e: e["type"] == "caption" and e["kind"] == "original")
        assert orig["speakerName"] == "Rahul" and orig["lang"] == "hi"
        final = drain_until(wb, lambda e: e["type"] == "caption" and e["kind"] == "translation" and e["final"])
        assert final["lang"] == "en" and final["text"].startswith("[English]")
        assert final["timings"]["e2e_ms"] >= SETTINGS.vad_hangover_ms

    m = client.get("/api/metrics").json()
    assert m["stages"]["e2e_final_ms"]["count"] >= 1


def test_listener_with_same_language_gets_only_original(client):
    a = join(client, room="same-lang", name="A", speak="en", listen="en")
    b = join(client, room="same-lang", name="B", speak="en", listen="en")
    with client.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa, \
         client.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
        wa.receive_json(); wb.receive_json()
        for c in chunks(utterance_audio()):
            wa.send_bytes(c)
        drain_until(wb, lambda e: e["type"] == "caption" and e["kind"] == "original")
        wa.send_json({"type": "ping", "t": 1})
        wb.send_json({"type": "ping", "t": 2})
        seen = []
        while True:
            ev = wb.receive_json()
            if ev["type"] == "pong":
                break
            seen.append(ev)
        assert not [e for e in seen if e["type"] == "caption" and e["kind"] == "translation"]


def test_rooms_are_isolated(client):
    a = join(client, room="room-one", name="A", speak="hi", listen="hi")
    b = join(client, room="room-two", name="B", speak="en", listen="en")
    with client.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa, \
         client.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
        wa.receive_json(); wb.receive_json()
        for c in chunks(utterance_audio()):
            wa.send_bytes(c)
        wb.send_json({"type": "ping", "t": 9})
        evs = []
        while True:
            ev = wb.receive_json()
            if ev["type"] == "pong":
                break
            evs.append(ev)
        assert not [e for e in evs if e["type"] == "caption"]


def test_bad_pref_is_reported(client):
    a = join(client, room="pref-room")
    with client.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa:
        wa.receive_json()
        wa.send_json({"type": "prefs", "listen": "klingon"})
        ev = drain_until(wa, lambda e: e["type"] == "status")
        assert ev["code"] == "bad_prefs"


def test_room_capacity_enforced():
    s = Settings(provider="mock", jwt_secret="capacity-test-secret-capacity-test-123",
                 livekit_api_secret="livekit-test-secret-livekit-test-secret", max_participants_per_room=1)
    with TestClient(create_app(s)) as c:
        a = join(c, room="tiny-room", name="A")
        b = join(c, room="tiny-room", name="B")
        with c.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa:
            wa.receive_json()
            with c.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
                ev = drain_until(wb, lambda e: e["type"] == "status")
                assert ev["code"] == "room_full"


def test_glossary_is_capped_and_broadcast(client):
    a = join(client, room="gloss-room")
    with client.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa:
        wa.receive_json()
        wa.send_json({"type": "glossary", "terms": ["RepoMind", "  ", "x" * 200] + [f"t{i}" for i in range(80)]})
        ev = drain_until(wa, lambda e: e["type"] == "roster" and e["glossary"])
        assert ev["glossary"][0] == "RepoMind"
        assert len(ev["glossary"]) <= 50 and all(len(t) <= 60 for t in ev["glossary"])
