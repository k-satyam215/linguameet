import math
import struct

from app.vad import FRAME_SAMPLES, SAMPLE_RATE


def tone(ms: int, amp: int = 8000, freq: float = 220.0) -> bytes:
    n = SAMPLE_RATE * ms // 1000
    return struct.pack(f"<{n}h", *(int(amp * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)) for i in range(n)))


def silence(ms: int) -> bytes:
    return b"\x00\x00" * (SAMPLE_RATE * ms // 1000)


def utterance_audio(speech_ms: int = 700, tail_ms: int = 800) -> bytes:
    """Silence, a burst of 'speech', then enough silence to close the segment."""
    return silence(200) + tone(speech_ms) + silence(tail_ms)


def chunks(data: bytes, ms: int = 40):
    step = SAMPLE_RATE * ms // 1000 * 2
    for i in range(0, len(data), step):
        yield data[i:i + step]


assert FRAME_SAMPLES == 320
