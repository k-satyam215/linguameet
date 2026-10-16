"""FastAPI entrypoint: join API, language list, metrics and the translation WebSocket."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import auth
from .config import Settings
from .languages import DEFAULT_REGISTRY, LanguageRegistry
from .latency import Metrics
from .livekit_admin import LiveKitAdmin, LiveKitAdminError
from .pipeline import TranslationPipeline
from .providers import build_providers
from .rooms import RoomFull, RoomManager

MAX_AUDIO_CHUNK = 64 * 1024  # bytes per WS frame; real chunks are ~1 KB


class HostAction(BaseModel):
    target: str = ""
    locked: bool = False


class JoinRequest(BaseModel):
    room: str
    name: str = Field(min_length=1, max_length=40)
    speak: str = "en"
    listen: str = "en"


def create_app(settings: Settings | None = None, registry: LanguageRegistry | None = None,
               asr=None, translator=None, admin=None) -> FastAPI:
    settings = settings or Settings.from_env()
    registry = registry or DEFAULT_REGISTRY
    if asr is None or translator is None:
        asr, translator, provider_name = build_providers(settings)
    else:
        provider_name = "injected"
    metrics = Metrics()
    pipeline = TranslationPipeline(asr, translator, registry, metrics, settings)
    manager = RoomManager(pipeline, registry, settings)
    admin = admin or LiveKitAdmin(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await translator.aclose()
        await admin.aclose()

    app = FastAPI(title="LinguaMeet API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"], allow_headers=["authorization", "content-type"],
    )
    app.state.manager = manager
    app.state.metrics = metrics
    app.state.settings = settings

    @app.get("/api/health")
    async def health():
        return {"ok": True, "provider": provider_name, "rooms": len(manager.rooms)}

    @app.get("/api/languages")
    async def languages():
        return {"languages": registry.public()}

    @app.get("/api/metrics")
    async def get_metrics():
        return metrics.summary()

    @app.post("/api/join")
    async def join(req: JoinRequest):
        if not auth.valid_room(req.room):
            raise HTTPException(400, "Room code must be 3-40 chars: letters, digits, - or _")
        if req.speak != "auto" and not registry.can_speak(req.speak):
            raise HTTPException(400, f"Unsupported spoken language: {req.speak}")
        if not registry.can_listen(req.listen):
            raise HTTPException(400, f"Unsupported listening language: {req.listen}")
        name = req.name.strip()
        if not name:
            raise HTTPException(400, "Name is required")
        if manager.is_locked(req.room):
            raise HTTPException(423, "This meeting is locked by the host.")
        identity = auth.new_identity()
        return {
            "identity": identity,
            "livekit_url": settings.livekit_url,
            "livekit_token": auth.livekit_token(settings, req.room, identity, name),
            "ws_token": auth.ws_token(settings, req.room, identity, name, req.speak, req.listen),
        }

    def _host(authorization: str) -> dict:
        claims = auth.verify_ws_token(settings, authorization.removeprefix("Bearer ").strip())
        if claims is None:
            raise HTTPException(401, "Invalid or expired session")
        if not manager.is_host(claims["room"], claims["sub"]):
            raise HTTPException(403, "Only the host can do this")
        return claims

    @app.post("/api/host/mute")
    async def host_mute(req: HostAction, authorization: str = Header("")):
        c = _host(authorization)
        room = manager.rooms[c["room"]]
        try:
            if req.target == "*":
                n = await admin.mute_all(c["room"], {c["sub"]})
            elif req.target in room.participants:
                n = await admin.mute(c["room"], req.target)
            else:
                raise HTTPException(404, "Participant not in room")
        except LiveKitAdminError as e:
            raise HTTPException(502, str(e))
        return {"muted": n}

    @app.post("/api/host/remove")
    async def host_remove(req: HostAction, authorization: str = Header("")):
        c = _host(authorization)
        if req.target == c["sub"]:
            raise HTTPException(400, "You cannot remove yourself")
        if req.target not in manager.rooms[c["room"]].participants:
            raise HTTPException(404, "Participant not in room")
        try:
            await admin.remove(c["room"], req.target)
        except LiveKitAdminError as e:
            raise HTTPException(502, str(e))
        await manager.kick(c["room"], req.target)
        return {"removed": req.target}

    @app.post("/api/host/lock")
    async def host_lock(req: HostAction, authorization: str = Header("")):
        c = _host(authorization)
        await manager.set_locked(c["room"], req.locked)
        return {"locked": req.locked}

    @app.websocket("/ws/translate")
    async def ws_translate(ws: WebSocket, token: str = ""):
        claims = auth.verify_ws_token(settings, token)
        if claims is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        room_code = claims["room"]
        await ws.send_json({"type": "ready", "identity": claims["sub"], "provider": provider_name})
        try:
            p = await manager.join(room_code, claims["sub"], claims["name"], ws, claims["speak"], claims["listen"])
        except RoomFull as e:
            await ws.send_json({"type": "status", "code": "room_full", "message": str(e)})
            await ws.close(code=4403)
            return
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    data = msg["bytes"]
                    if len(data) <= MAX_AUDIO_CHUNK:
                        await manager.on_audio(room_code, p, data)
                elif msg.get("text") is not None:
                    await _handle_text(manager, room_code, p, msg["text"], ws)
        except WebSocketDisconnect:
            pass
        finally:
            await manager.leave(room_code, p)

    return app


async def _handle_text(manager: RoomManager, room_code: str, p, raw: str, ws: WebSocket) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    kind = msg.get("type")
    if kind == "prefs":
        err = await manager.set_prefs(room_code, p, msg.get("speak"), msg.get("listen"))
        if err:
            await ws.send_json({"type": "status", "code": "bad_prefs", "message": err})
    elif kind == "glossary":
        terms = msg.get("terms")
        if isinstance(terms, list):
            manager.set_glossary(room_code, terms)
            await manager.broadcast_roster(manager.rooms[room_code])
    elif kind == "ping":
        await ws.send_json({"type": "pong", "t": msg.get("t")})
    elif kind == "flush":
        seg = p.segmenter.flush()
        if seg and not p.queue.full():
            p.queue.put_nowait(seg)


app = None  # created lazily by `uvicorn app.main:get_app --factory`


def get_app() -> FastAPI:
    return create_app()
