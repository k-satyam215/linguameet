"""In-memory rooms: participants, language preferences and audio fan-out."""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import Settings
from .languages import LanguageRegistry
from .pipeline import TranslationPipeline, Utterance
from .vad import VadConfig, VadSegmenter


class Socket(Protocol):
    async def send_json(self, data: Any) -> None: ...


@dataclass
class Participant:
    identity: str
    name: str
    ws: Socket
    speak: str
    listen: str
    segmenter: VadSegmenter
    queue: "asyncio.Queue[Any]" = field(default_factory=lambda: asyncio.Queue(maxsize=20))
    task: asyncio.Task | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=4))


class Room:
    def __init__(self, code: str) -> None:
        self.code = code
        self.participants: dict[str, Participant] = {}
        self.glossary: list[str] = []
        self.host: str | None = None
        self.locked = False

    def roster(self) -> list[dict]:
        return [
            {"identity": p.identity, "name": p.name, "speak": p.speak, "listen": p.listen}
            for p in self.participants.values()
        ]


class RoomFull(Exception):
    pass


class RoomManager:
    def __init__(self, pipeline: TranslationPipeline, registry: LanguageRegistry, settings: Settings) -> None:
        self.pipeline = pipeline
        self.registry = registry
        self.settings = settings
        self.rooms: dict[str, Room] = {}

    # ---- membership ------------------------------------------------------
    async def join(self, code: str, identity: str, name: str, ws: Socket, speak: str, listen: str) -> Participant:
        room = self.rooms.get(code)
        if room is None:
            if len(self.rooms) >= self.settings.max_rooms:
                raise RoomFull("server has too many active rooms")
            room = self.rooms[code] = Room(code)
        if identity not in room.participants and len(room.participants) >= self.settings.max_participants_per_room:
            raise RoomFull("room is full")
        old = room.participants.get(identity)
        if old and old.task:
            old.task.cancel()
        cfg = VadConfig(
            hangover_ms=self.settings.vad_hangover_ms,
            min_speech_ms=self.settings.vad_min_speech_ms,
            max_segment_ms=self.settings.vad_max_segment_ms,
            min_rms=self.settings.vad_min_rms,
        )
        p = Participant(identity, name, ws, speak, listen, VadSegmenter(cfg))
        p.task = asyncio.create_task(self._worker(room, p))
        room.participants[identity] = p
        if room.host is None or room.host not in room.participants:
            room.host = identity
        await self.broadcast_roster(room)
        return p

    async def leave(self, code: str, p: Participant) -> None:
        room = self.rooms.get(code)
        if not room or room.participants.get(p.identity) is not p:
            return
        del room.participants[p.identity]
        if p.task:
            p.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await p.task
        if not room.participants:
            self.rooms.pop(code, None)
        else:
            if room.host == p.identity:  # promote the longest-present participant
                room.host = next(iter(room.participants))
            await self.broadcast_roster(room)

    async def set_prefs(self, code: str, p: Participant, speak: str | None, listen: str | None) -> str | None:
        """Returns an error string if the preference is not supported."""
        if speak is not None:
            if not self.registry.can_speak(speak) and speak != "auto":
                return f"unsupported spoken language: {speak}"
            p.speak = speak
        if listen is not None:
            if not self.registry.can_listen(listen):
                return f"unsupported listening language: {listen}"
            p.listen = listen
        room = self.rooms.get(code)
        if room:
            await self.broadcast_roster(room)
        return None

    def set_glossary(self, code: str, terms: list[str]) -> None:
        room = self.rooms.get(code)
        if room:
            clean = [t.strip()[:60] for t in terms if isinstance(t, str) and t.strip()]
            room.glossary = clean[:50]

    # ---- host actions ----------------------------------------------------
    def is_host(self, code: str, identity: str) -> bool:
        room = self.rooms.get(code)
        return bool(room and room.host == identity)

    async def set_locked(self, code: str, locked: bool) -> None:
        room = self.rooms.get(code)
        if room:
            room.locked = locked
            await self.broadcast_roster(room)

    def is_locked(self, code: str) -> bool:
        room = self.rooms.get(code)
        return bool(room and room.locked)

    async def kick(self, code: str, identity: str) -> bool:
        room = self.rooms.get(code)
        p = room.participants.get(identity) if room else None
        if p is None:
            return False
        await self._send(p, {"type": "status", "code": "removed", "message": "You were removed from the meeting by the host."})
        close = getattr(p.ws, "close", None)
        if close:
            try:
                await close(code=4410)
            except Exception:
                pass
        return True

    # ---- audio -----------------------------------------------------------
    async def on_audio(self, code: str, p: Participant, data: bytes) -> None:
        for seg in p.segmenter.feed(data):
            if p.queue.full():
                await self._send(p, {"type": "status", "code": "overloaded",
                                     "message": "Translation is behind; one sentence was skipped."})
                self.pipeline.metrics.incr("queue_full_dropped")
                continue
            p.queue.put_nowait(seg)

    async def _worker(self, room: Room, p: Participant) -> None:
        """Process one speaker's utterances in order."""
        while True:
            seg = await p.queue.get()
            targets = {
                q.listen for q in room.participants.values()
                if q.identity != p.identity
            }
            utt = Utterance(p.identity, p.name, p.speak, seg)
            try:
                text = await self.pipeline.process(
                    utt, targets, list(room.glossary), list(p.history),
                    lambda aud, ev, _p=p, _r=room: self._emit(_r, _p, aud, ev),
                )
                if text:
                    p.history.append(text)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let one bad utterance kill the worker
                self.pipeline.metrics.incr("pipeline_errors")
                await self._send(p, {"type": "status", "code": "internal", "message": f"pipeline error: {type(e).__name__}"})

    # ---- delivery --------------------------------------------------------
    async def _emit(self, room: Room, speaker: Participant, audience: str, event: dict) -> None:
        if audience == "*speaker":
            recipients = [speaker]
        elif audience == "*all":
            recipients = list(room.participants.values())
        elif audience.startswith("lang:"):
            lang = audience[5:]
            recipients = [q for q in room.participants.values() if q.identity != speaker.identity and q.listen == lang]
        else:
            recipients = []
        await asyncio.gather(*(self._send(q, event) for q in recipients))

    async def _send(self, p: Participant, event: dict) -> None:
        try:
            await p.ws.send_json(event)
        except Exception:
            pass  # socket is closing; the receive loop will clean up

    async def broadcast_roster(self, room: Room) -> None:
        ev = {"type": "roster", "participants": room.roster(), "glossary": room.glossary,
              "host": room.host, "locked": room.locked}
        await asyncio.gather(*(self._send(q, ev) for q in room.participants.values()))
