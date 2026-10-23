"""Energy-based VAD + utterance segmenter for 16 kHz mono PCM16."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2


@dataclass
class VadConfig:
    hangover_ms: int = 250
    min_speech_ms: int = 250
    max_segment_ms: int = 9000
    min_rms: float = 300.0
    noise_ratio: float = 3.0
    start_frames: int = 3
    preroll_ms: int = 200


@dataclass
class Segment:
    pcm: bytes
    duration_ms: int
    detected_at: float
    hangover_ms: int
    forced: bool = False
    start_sample: int = 0
    end_sample: int = 0
    detected_sample: int = 0


class VadSegmenter:
    def __init__(self, cfg: VadConfig | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg or VadConfig()
        self._clock = clock
        self._rem = b""
        self._frames_seen = 0
        self._start_frame: int | None = None
        self._noise = 100.0
        self._speaking = False
        self._run = 0
        self._silence = 0
        self._voiced = 0
        self._buf: list[bytes] = []
        pre = max(1, self.cfg.preroll_ms // FRAME_MS) + self.cfg.start_frames
        self._pre: deque[bytes] = deque(maxlen=pre)
        self._hang_frames = max(1, self.cfg.hangover_ms // FRAME_MS)
        self._max_frames = max(1, self.cfg.max_segment_ms // FRAME_MS)

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _rms(self, frame: bytes) -> float:
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(x * x))) if x.size else 0.0

    def feed(self, data: bytes) -> list[Segment]:
        out: list[Segment] = []
        data = self._rem + data
        n = len(data) // FRAME_BYTES
        for i in range(n):
            seg = self._frame(data[i * FRAME_BYTES:(i + 1) * FRAME_BYTES])
            if seg:
                out.append(seg)
        self._rem = data[n * FRAME_BYTES:]
        return out

    def _threshold(self) -> float:
        return max(self.cfg.min_rms, self._noise * self.cfg.noise_ratio)

    def _frame(self, frame: bytes) -> Segment | None:
        frame_index = self._frames_seen
        self._frames_seen += 1
        rms = self._rms(frame)
        voiced = rms > self._threshold()
        if not self._speaking:
            self._pre.append(frame)
            if not voiced:
                self._noise = max(30.0, 0.95 * self._noise + 0.05 * rms)
                self._run = 0
                return None
            self._run += 1
            if self._run >= self.cfg.start_frames:
                self._speaking = True
                self._buf = list(self._pre)
                self._start_frame = frame_index + 1 - len(self._pre)
                self._voiced = self._run
                self._silence = 0
            return None

        self._buf.append(frame)
        if voiced:
            self._voiced += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self._hang_frames:
            return self._close(forced=False)
        if len(self._buf) >= self._max_frames:
            return self._close(forced=True)
        return None

    def _close(self, forced: bool) -> Segment | None:
        voiced_ms = self._voiced * FRAME_MS
        frames = self._buf
        trim = max(0, self._silence - 3)
        if trim and not forced:
            frames = frames[:-trim]
        start_frame = self._start_frame or 0
        detected_sample = self._frames_seen * FRAME_SAMPLES
        self._reset()
        if voiced_ms < self.cfg.min_speech_ms:
            return None
        return Segment(
            pcm=b"".join(frames), duration_ms=len(frames) * FRAME_MS,
            detected_at=self._clock(), hangover_ms=0 if forced else self.cfg.hangover_ms,
            forced=forced, start_sample=start_frame * FRAME_SAMPLES,
            end_sample=(start_frame + len(frames)) * FRAME_SAMPLES,
            detected_sample=detected_sample,
        )

    def _reset(self) -> None:
        self._speaking = False
        self._run = 0
        self._silence = 0
        self._voiced = 0
        self._buf = []
        self._start_frame = None
        self._pre.clear()

    def flush(self) -> Segment | None:
        return self._close(forced=True) if self._speaking else None

