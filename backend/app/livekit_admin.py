"""Server-side LiveKit admin calls (mute / remove) over the Twirp JSON API.

The browser never gets admin rights: the host asks OUR API, we check they are
the host, and only then call LiveKit with a short-lived roomAdmin token.

NOTE: request shapes follow LiveKit's documented RoomService Twirp API but have
only been tested against a fake transport, not a live LiveKit server.
"""
from __future__ import annotations

import time

import httpx
import jwt

from .config import Settings


class LiveKitAdminError(Exception):
    pass


def _http_base(settings: Settings) -> str:
    base = getattr(settings, "livekit_http_url", "") or settings.livekit_url
    return base.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")


class LiveKitAdmin:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=5.0)

    def _token(self, room: str) -> str:
        now = int(time.time())
        claims = {
            "iss": self._s.livekit_api_key, "nbf": now - 5, "exp": now + 60,
            "video": {"room": room, "roomAdmin": True},
        }
        return jwt.encode(claims, self._s.livekit_api_secret, algorithm="HS256")

    async def _call(self, method: str, room: str, body: dict) -> dict:
        try:
            r = await self._client.post(
                f"{_http_base(self._s)}/twirp/livekit.RoomService/{method}",
                headers={"Authorization": f"Bearer {self._token(room)}"},
                json=body,
            )
        except httpx.HTTPError as e:
            raise LiveKitAdminError(f"video server unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise LiveKitAdminError(f"{method} failed ({r.status_code})")
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {}

    async def list_participants(self, room: str) -> list[dict]:
        return (await self._call("ListParticipants", room, {"room": room})).get("participants", [])

    @staticmethod
    def _mic_sids(participant: dict) -> list[str]:
        out = []
        for t in participant.get("tracks", []) or []:
            is_mic = str(t.get("source", "")).upper() == "MICROPHONE" or str(t.get("type", "")).upper() == "AUDIO"
            if is_mic and not t.get("muted") and t.get("sid"):
                out.append(t["sid"])
        return out

    async def _mute_participant(self, room: str, p: dict) -> int:
        n = 0
        for sid in self._mic_sids(p):
            await self._call("MutePublishedTrack", room, {"room": room, "identity": p.get("identity"), "trackSid": sid, "muted": True})
            n += 1
        return n

    async def mute(self, room: str, identity: str) -> int:
        for p in await self.list_participants(room):
            if p.get("identity") == identity:
                return await self._mute_participant(room, p)
        return 0

    async def mute_all(self, room: str, exclude: set[str]) -> int:
        n = 0
        for p in await self.list_participants(room):
            if p.get("identity") not in exclude:
                n += await self._mute_participant(room, p)
        return n

    async def remove(self, room: str, identity: str) -> None:
        await self._call("RemoveParticipant", room, {"room": room, "identity": identity})

    async def aclose(self) -> None:
        await self._client.aclose()
