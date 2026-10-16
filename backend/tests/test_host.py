import json

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.livekit_admin import LiveKitAdmin, LiveKitAdminError
from app.main import create_app

LK_SECRET = "livekit-test-secret-livekit-test-secret"
SETTINGS = Settings(provider="mock", jwt_secret="host-test-secret-host-test-secret-123", livekit_api_key="k",
                    livekit_api_secret=LK_SECRET)


class FakeAdmin:
    def __init__(self):
        self.calls = []

    async def mute(self, room, identity):
        self.calls.append(("mute", room, identity))
        return 1

    async def mute_all(self, room, exclude):
        self.calls.append(("mute_all", room, sorted(exclude)))
        return 2

    async def remove(self, room, identity):
        self.calls.append(("remove", room, identity))

    async def aclose(self):
        pass


@pytest.fixture
def env():
    admin = FakeAdmin()
    with TestClient(create_app(SETTINGS, admin=admin)) as c:
        yield c, admin


def join(c, room="host-room", name="A"):
    r = c.post("/api/join", json={"room": room, "name": name, "speak": "en", "listen": "en"})
    return r


def hdr(j):
    return {"Authorization": f"Bearer {j['ws_token']}"}


def drain(ws, pred, limit=40):
    for _ in range(limit):
        ev = ws.receive_json()
        if pred(ev):
            return ev
    raise AssertionError("event never arrived")


def open_two(c, room="host-room"):
    a, b = join(c, room, "Host").json(), join(c, room, "Guest").json()
    return a, b


def test_first_joiner_is_host_and_roster_says_so(env):
    c, _ = env
    a, b = open_two(c)
    with c.websocket_connect(f"/ws/translate?token={a['ws_token']}") as wa, \
         c.websocket_connect(f"/ws/translate?token={b['ws_token']}"):
        ev = drain(wa, lambda e: e["type"] == "roster" and len(e["participants"]) == 2)
        assert ev["host"] == a["identity"] and ev["locked"] is False


def test_non_host_and_anonymous_are_rejected(env):
    c, admin = env
    a, b = open_two(c)
    with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"), \
         c.websocket_connect(f"/ws/translate?token={b['ws_token']}"):
        assert c.post("/api/host/mute", json={"target": "*"}, headers=hdr(b)).status_code == 403
        assert c.post("/api/host/remove", json={"target": a["identity"]}, headers=hdr(b)).status_code == 403
        assert c.post("/api/host/lock", json={"locked": True}, headers=hdr(b)).status_code == 403
        assert c.post("/api/host/mute", json={"target": "*"}).status_code == 401
        assert c.post("/api/host/mute", json={"target": "*"}, headers={"Authorization": "Bearer junk"}).status_code == 401
    assert admin.calls == []


def test_host_can_mute_one_and_all(env):
    c, admin = env
    a, b = open_two(c)
    with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"), \
         c.websocket_connect(f"/ws/translate?token={b['ws_token']}"):
        assert c.post("/api/host/mute", json={"target": b["identity"]}, headers=hdr(a)).json() == {"muted": 1}
        assert c.post("/api/host/mute", json={"target": "*"}, headers=hdr(a)).json() == {"muted": 2}
        assert c.post("/api/host/mute", json={"target": "u_nobody"}, headers=hdr(a)).status_code == 404
    assert admin.calls[0] == ("mute", "host-room", b["identity"])
    assert admin.calls[1] == ("mute_all", "host-room", [a["identity"]])   # host is never muted by mute-all


def test_host_remove_kicks_ws_and_cannot_remove_self(env):
    c, admin = env
    a, b = open_two(c)
    with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"), \
         c.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
        assert c.post("/api/host/remove", json={"target": a["identity"]}, headers=hdr(a)).status_code == 400
        assert c.post("/api/host/remove", json={"target": b["identity"]}, headers=hdr(a)).status_code == 200
        ev = drain(wb, lambda e: e["type"] == "status")
        assert ev["code"] == "removed"
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(10):
                wb.receive_json()
        assert exc.value.code == 4410
    assert ("remove", "host-room", b["identity"]) in admin.calls


def test_lock_blocks_new_joins_until_unlocked(env):
    c, _ = env
    a = join(c, "lock-room", "Host").json()
    with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"):
        assert c.post("/api/host/lock", json={"locked": True}, headers=hdr(a)).json() == {"locked": True}
        assert join(c, "lock-room", "Late").status_code == 423
        assert c.post("/api/host/lock", json={"locked": False}, headers=hdr(a)).status_code == 200
        assert join(c, "lock-room", "Late").status_code == 200


def test_host_is_promoted_when_host_leaves(env):
    c, _ = env
    a, b = open_two(c)
    with c.websocket_connect(f"/ws/translate?token={b['ws_token']}") as wb:
        with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"):
            drain(wb, lambda e: e["type"] == "roster" and len(e["participants"]) == 2)
        ev = drain(wb, lambda e: e["type"] == "roster" and len(e["participants"]) == 1)
        assert ev["host"] == b["identity"]
        assert c.post("/api/host/lock", json={"locked": True}, headers=hdr(b)).status_code == 200


def test_host_failure_from_video_server_is_502():
    class Broken(FakeAdmin):
        async def mute_all(self, room, exclude):
            raise LiveKitAdminError("video server unreachable")

    with TestClient(create_app(SETTINGS, admin=Broken())) as c:
        a = join(c).json()
        with c.websocket_connect(f"/ws/translate?token={a['ws_token']}"):
            r = c.post("/api/host/mute", json={"target": "*"}, headers=hdr(a))
            assert r.status_code == 502


# ---- the real admin client against a fake LiveKit transport --------------------------------

async def test_livekit_admin_request_shapes():
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((req.url.path, req.headers["authorization"], body))
        if req.url.path.endswith("ListParticipants"):
            return httpx.Response(200, json={"participants": [
                {"identity": "u1", "tracks": [{"sid": "TR_a", "type": "AUDIO", "source": "MICROPHONE", "muted": False},
                                              {"sid": "TR_v", "type": "VIDEO", "source": "CAMERA"}]},
                {"identity": "u2", "tracks": [{"sid": "TR_b", "type": "AUDIO", "source": "MICROPHONE", "muted": True}]},
                {"identity": "host", "tracks": [{"sid": "TR_h", "type": "AUDIO", "source": "MICROPHONE"}]},
            ]})
        return httpx.Response(200, json={})

    admin = LiveKitAdmin(Settings(livekit_url="ws://lk:7880", livekit_api_key="k", livekit_api_secret=LK_SECRET),
                         httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await admin.mute("room-x", "u1") == 1                      # only the unmuted mic track
    assert await admin.mute_all("room-x", {"host"}) == 1              # u1 only: u2 already muted, host excluded
    await admin.remove("room-x", "u2")

    path, auth, body = seen[1]
    assert path == "/twirp/livekit.RoomService/MutePublishedTrack"
    assert body == {"room": "room-x", "identity": "u1", "trackSid": "TR_a", "muted": True}
    claims = jwt.decode(auth.removeprefix("Bearer "), LK_SECRET, algorithms=["HS256"])
    assert claims["iss"] == "k" and claims["video"] == {"room": "room-x", "roomAdmin": True}
    assert seen[-1][0] == "/twirp/livekit.RoomService/RemoveParticipant"
    assert seen[-1][2] == {"room": "room-x", "identity": "u2"}


async def test_livekit_admin_errors_are_wrapped():
    admin = LiveKitAdmin(SETTINGS, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    with pytest.raises(LiveKitAdminError):
        await admin.remove("r", "u")

    def boom(req):
        raise httpx.ConnectError("down")

    admin = LiveKitAdmin(SETTINGS, httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(LiveKitAdminError):
        await admin.mute("r", "u")


def test_cors_preflight_allows_authorization_header(env):
    c, _ = env
    r = c.options("/api/host/mute", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
