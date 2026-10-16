"""Tokens: LiveKit access tokens and our own WebSocket tokens (both HS256 JWTs)."""
from __future__ import annotations

import re
import time
import uuid

import jwt

from .config import Settings

ROOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,39}$")


def valid_room(code: str) -> bool:
    return bool(ROOM_RE.match(code or ""))


def new_identity() -> str:
    return "u_" + uuid.uuid4().hex[:10]


def livekit_token(s: Settings, room: str, identity: str, name: str) -> str:
    now = int(time.time())
    claims = {
        "iss": s.livekit_api_key,
        "sub": identity,
        "name": name,
        "nbf": now - 5,
        "exp": now + s.token_ttl_s,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    return jwt.encode(claims, s.livekit_api_secret, algorithm="HS256")


def ws_token(s: Settings, room: str, identity: str, name: str, speak: str, listen: str) -> str:
    now = int(time.time())
    claims = {
        "aud": "translate-ws", "room": room, "sub": identity, "name": name,
        "speak": speak, "listen": listen, "iat": now, "exp": now + s.token_ttl_s,
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def verify_ws_token(s: Settings, token: str) -> dict | None:
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"], audience="translate-ws")
    except jwt.PyJWTError:
        return None
