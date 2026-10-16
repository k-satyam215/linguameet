"""Measure real pipeline latency on YOUR recordings with the configured provider.

    cd backend
    GROQ_API_KEY=... python -m scripts.bench path/to/hindi.wav --speak hi-en --listen en

Input: 16 kHz mono 16-bit WAV (convert with: ffmpeg -i in.m4a -ar 16000 -ac 1 out.wav).
Prints per-stage p50/p95. Run it several times, on your real network, before trusting any number.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import wave

from app.config import Settings
from app.languages import DEFAULT_REGISTRY
from app.latency import Metrics
from app.pipeline import TranslationPipeline, Utterance
from app.providers import build_providers
from app.vad import VadConfig, VadSegmenter


def _is_pcm16k_wav(path: str) -> bool:
    try:
        with wave.open(path, "rb") as w:
            return (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    except (wave.Error, EOFError):
        return False


def load_pcm(path: str) -> bytes:
    """Load 16 kHz mono PCM16. Any other format (m4a/mp3/ogg/stereo wav) is converted with ffmpeg."""
    if not _is_pcm16k_wav(path):
        if not shutil.which("ffmpeg"):
            raise SystemExit("Input is not 16 kHz mono 16-bit WAV and ffmpeg is not installed to convert it.")
        out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", out], check=True)
        path = out
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes())


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--speak", default="hi-en")
    ap.add_argument("--listen", default="en")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()

    settings = Settings.from_env()
    asr, translator, name = build_providers(settings)
    metrics = Metrics()
    pipe = TranslationPipeline(asr, translator, DEFAULT_REGISTRY, metrics, settings)
    pcm = load_pcm(a.wav)
    print(f"provider={name} audio={len(pcm) / 32000:.1f}s runs={a.runs}")

    for run in range(a.runs):
        seg = VadSegmenter(VadConfig(hangover_ms=settings.vad_hangover_ms, max_segment_ms=60000))
        segments = []
        step = 640
        for i in range(0, len(pcm), step):
            segments.extend(seg.feed(pcm[i:i + step]))
        tail = seg.flush()
        if tail:
            segments.append(tail)
        for s in segments:
            s.detected_at = time.monotonic()

            async def emit(aud: str, ev: dict, run: int = run) -> None:
                if ev.get("type") == "caption" and ev.get("final") and ev["kind"] == "translation":
                    print(f"run {run}: {ev['text']!r}  {json.dumps(ev['timings'])}")
                elif ev.get("type") == "status":
                    print(f"run {run}: STATUS {ev['code']}: {ev['message']}")

            await pipe.process(Utterance("bench", "Bench", a.speak, s), {a.listen}, [], [], emit)

    print(json.dumps(metrics.summary()["stages"], indent=2))
    await translator.aclose()


if __name__ == "__main__":
    asyncio.run(main())
