"""Run a repeatable energy-VAD sweep against hand-labelled speech intervals."""
from __future__ import annotations

import argparse
import itertools
import json
import time
import wave
from pathlib import Path

from app.vad import FRAME_BYTES, SAMPLE_RATE, VadConfig, VadSegmenter


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError("WAV must be 16 kHz, mono, PCM16")
        return wav.readframes(wav.getnframes()), wav.getnframes()


def collect_segments(pcm: bytes, cfg: VadConfig) -> tuple[list[tuple[int, int, int]], float]:
    segmenter = VadSegmenter(cfg)
    intervals = []
    started = time.perf_counter()
    for offset in range(0, len(pcm), FRAME_BYTES * 5):
        intervals.extend(
            (s.start_sample, s.end_sample, s.detected_sample)
            for s in segmenter.feed(pcm[offset:offset + FRAME_BYTES * 5])
        )
    tail = segmenter.flush()
    if tail:
        intervals.append((tail.start_sample, tail.end_sample, tail.detected_sample))
    return intervals, (time.perf_counter() - started) * 1000


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    intersection = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union else 0.0


def score_intervals(
    predicted: list[tuple[int, int, int]], reference: list[tuple[int, int]], threshold: float = 0.2
) -> dict:
    candidates = sorted(
        ((_iou((p[0], p[1]), r), pi, ri) for pi, p in enumerate(predicted) for ri, r in enumerate(reference)),
        reverse=True,
    )
    used_predictions: set[int] = set()
    used_references: set[int] = set()
    matches = []
    for overlap, pi, ri in candidates:
        if overlap < threshold:
            break
        if pi not in used_predictions and ri not in used_references:
            used_predictions.add(pi)
            used_references.add(ri)
            matches.append((predicted[pi], reference[ri]))
    start_errors = [abs(p[0] - r[0]) * 1000 / SAMPLE_RATE for p, r in matches]
    end_errors = [abs(p[1] - r[1]) * 1000 / SAMPLE_RATE for p, r in matches]
    decision_delays = [(p[2] - r[1]) * 1000 / SAMPLE_RATE for p, r in matches]
    tp, fp, fn = len(matches), len(predicted) - len(matches), len(reference) - len(matches)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "reference_segments": len(reference), "predicted_segments": len(predicted),
        "matched_segments": tp, "false_activations": fp, "missed_segments": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "mean_abs_start_error_ms": sum(start_errors) / len(start_errors) if start_errors else None,
        "mean_abs_end_error_ms": sum(end_errors) / len(end_errors) if end_errors else None,
        "mean_decision_delay_ms": sum(decision_delays) / len(decision_delays) if decision_delays else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("annotations", type=Path, help="JSON: {segments:[{start_ms,end_ms},...]}")
    parser.add_argument("--hangovers", default="150,250,350,450")
    parser.add_argument("--min-rms", default="200,300,500")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pcm, n_samples = read_wav(args.wav)
    labels = json.loads(args.annotations.read_text(encoding="utf-8"))
    reference = [
        (round(item["start_ms"] * SAMPLE_RATE / 1000), round(item["end_ms"] * SAMPLE_RATE / 1000))
        for item in labels["segments"]
    ]
    results = []
    for hangover, min_rms in itertools.product(
        [int(x) for x in args.hangovers.split(",")], [float(x) for x in args.min_rms.split(",")]
    ):
        predicted, runtime_ms = collect_segments(
            pcm, VadConfig(hangover_ms=hangover, min_rms=min_rms, max_segment_ms=60_000)
        )
        results.append({
            "hangover_ms": hangover, "min_rms": min_rms,
            "audio_duration_s": n_samples / SAMPLE_RATE,
            "processing_ms": round(runtime_ms, 2),
            "realtime_factor": runtime_ms / (n_samples * 1000 / SAMPLE_RATE) if n_samples else None,
            **score_intervals(predicted, reference),
        })
    report = {"schema_version": 1, "wav": args.wav.name, "results": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
