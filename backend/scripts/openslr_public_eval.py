"""Evaluate local Whisper ASR and energy VAD on an OpenSLR 104 test subset.

Input data remains local. The script never calls a hosted model/API and exports only
aggregate metrics, not the corpus transcripts or audio.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import time
import wave
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.evaluation import score_rows
from app.vad import FRAME_BYTES, SAMPLE_RATE, VadConfig, VadSegmenter
from scripts.vad_sweep import score_intervals


def read_member(archive, members: dict[str, object], name: str) -> bytes:
    member = members.get(name)
    if member is None:
        raise ValueError(f"archive is missing {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read {name}")
    return stream.read()


def parse_references(archive, members: dict[str, object]) -> tuple[dict[str, str], list[tuple[str, str, float, float]]]:
    texts = {}
    for line in read_member(archive, members, "test/transcripts/text").decode("utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if parts:
            texts[parts[0]] = parts[1] if len(parts) > 1 else ""
    segments = []
    for line in read_member(archive, members, "test/transcripts/segments").decode("utf-8").splitlines():
        utt, recording, start, end = line.split(maxsplit=3)
        if utt in texts:
            segments.append((utt, recording, float(start), float(end)))
    return texts, segments


def pick_subset(segments: list[tuple[str, str, float, float]], recordings: int, per_recording: int):
    grouped: dict[str, list[tuple[str, str, float, float]]] = defaultdict(list)
    for row in segments:
        grouped[row[1]].append(row)
    chosen = []
    for _name, rows in grouped.items():
        if len(rows) < per_recording:
            continue
        if per_recording == 1:
            indexes = [len(rows) // 2]
        else:
            indexes = [round(i * (len(rows) - 1) / (per_recording - 1)) for i in range(per_recording)]
        chosen.extend(rows[i] for i in indexes)
        if len({row[1] for row in chosen}) >= recordings:
            break
    return chosen, list(dict.fromkeys(row[1] for row in chosen))


def segment_audio(pcm: bytes, start: float, end: float, sample_rate: int) -> bytes:
    width = 2
    first = max(0, int(start * sample_rate))
    last = min(len(pcm) // width, int(end * sample_rate))
    return pcm[first * width:last * width]


def collect_vad(pcm: bytes, hangover: int, min_rms: float):
    segmenter = VadSegmenter(VadConfig(hangover_ms=hangover, min_rms=min_rms, max_segment_ms=60000))
    output = []
    for offset in range(0, len(pcm), FRAME_BYTES * 5):
        output.extend((s.start_sample, s.end_sample, s.detected_sample)
                      for s in segmenter.feed(pcm[offset:offset + FRAME_BYTES * 5]))
    tail = segmenter.flush()
    if tail:
        output.append((tail.start_sample, tail.end_sample, tail.detected_sample))
    return output


def summarize_vad(records: list[dict]) -> dict:
    tp = sum(row["matched_segments"] for row in records)
    fp = sum(row["false_activations"] for row in records)
    fn = sum(row["missed_segments"] for row in records)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    def mean(key):
        values = [row[key] for row in records if row[key] is not None]
        return sum(values) / len(values) if values else None
    return {
        "recordings": len(records), "reference_segments": sum(row["reference_segments"] for row in records),
        "predicted_segments": sum(row["predicted_segments"] for row in records),
        "matched_segments": tp, "false_activations": fp, "missed_segments": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "mean_abs_start_error_ms_macro": mean("mean_abs_start_error_ms"),
        "mean_abs_end_error_ms_macro": mean("mean_abs_end_error_ms"),
        "mean_decision_delay_ms_macro": mean("mean_decision_delay_ms"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="OpenSLR SLR104 Hindi-English test tar.gz")
    parser.add_argument("--output", type=Path, required=True, help="aggregate JSON result path")
    parser.add_argument("--model", default="small", help="faster-whisper model size (default: small)")
    parser.add_argument("--model-cache", type=Path, required=True, help="local model cache directory")
    parser.add_argument("--cpu-threads", type=int, default=2, help="CPU inference threads")
    parser.add_argument("--recordings", type=int, default=8)
    parser.add_argument("--per-recording", type=int, default=5)
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error("archive file does not exist")
    if args.recordings < 1 or args.per_recording < 1:
        parser.error("recordings and per-recording must be positive")

    import tarfile

    import ctranslate2
    import faster_whisper
    from faster_whisper import WhisperModel

    archive_hash = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    with tarfile.open(args.archive, "r:gz") as archive:
        members = {item.name: item for item in archive.getmembers()}
        references, all_segments = parse_references(archive, members)
        chosen, selected_recordings = pick_subset(all_segments, args.recordings, args.per_recording)
        if len(selected_recordings) < args.recordings:
            raise ValueError(f"archive provides only {len(selected_recordings)} eligible recordings")
        recordings = {}
        for recording in selected_recordings:
            wav_bytes = read_member(archive, members, f"test/{recording}.wav")
            with wave.open(io.BytesIO(wav_bytes), "rb") as source:
                if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                    raise ValueError(f"{recording} is not 16 kHz mono PCM16")
                pcm = source.readframes(source.getnframes())
            recordings[recording] = pcm

    out_dir = args.output.parent / f"{args.output.stem}_clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    model_load_started = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.cpu_threads,
                          download_root=str(args.model_cache))
    model_load_ms = round((time.perf_counter() - model_load_started) * 1000, 1)

    asr_rows = []
    for utt, recording, start, end in chosen:
        clip = segment_audio(recordings[recording], start, end, SAMPLE_RATE)
        clip_path = out_dir / f"{utt}.wav"
        with wave.open(str(clip_path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(SAMPLE_RATE)
            target.writeframes(clip)
        started = time.perf_counter()
        chunks, _ = model.transcribe(str(clip_path), language="hi", task="transcribe", beam_size=5, vad_filter=False)
        hypothesis = " ".join(part.text.strip() for part in chunks).strip()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        asr_rows.append({
            "id": utt, "model": f"faster-whisper-{args.model}-cpu-int8", "task": "asr",
            "language": "hi-en", "reference": references[utt], "hypothesis": hypothesis,
            "timings_ms": {"asr_ms": elapsed_ms},
        })

    asr_metrics = score_rows(asr_rows)
    selected_set = set(selected_recordings)
    reference_by_recording: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for _, recording, start, end in all_segments:
        if recording in selected_set:
            reference_by_recording[recording].append((round(start * SAMPLE_RATE), round(end * SAMPLE_RATE)))

    vad_results = []
    for hangover in (150, 250, 350, 450):
        for min_rms in (200, 300, 500):
            per_recording = []
            for recording in selected_recordings:
                predicted = collect_vad(recordings[recording], hangover, min_rms)
                per_recording.append(score_intervals(predicted, reference_by_recording[recording]))
            vad_results.append({
                "hangover_ms": hangover, "min_rms": min_rms,
                **summarize_vad(per_recording),
            })

    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "name": "MUCS 2021 SLR104 Hindi-English test set", "license": "CC BY-SA 4.0",
            "source": "https://www.openslr.org/104/", "archive_sha256": archive_hash,
            "recordings_used": len(selected_recordings), "reference_segments_for_vad": sum(len(v) for v in reference_by_recording.values()),
            "asr_utterances": len(asr_rows),
            "selection": "first N eligible recordings in archive transcript order; evenly spaced utterances within each recording",
        },
        "asr": {"model": f"faster-whisper {args.model} / CTranslate2 CPU int8", "model_load_ms": model_load_ms,
                "runtime": {"python": platform.python_version(), "ctranslate2": ctranslate2.__version__,
                            "faster_whisper": faster_whisper.__version__}, "metrics": asr_metrics},
        "vad_sweep": vad_results,
        "limitations": [
            "This is a public spoken-tutorial/code-switching benchmark subset, not spontaneous meeting speech or a participant pilot.",
            "Whisper is run with Hindi as the primary language; language-specific script and code-switch scoring policy affects WER/CER.",
            "VAD intervals use the corpus-provided transcript segment timestamps; boundary labels are not independent manual re-annotations.",
            "Translation quality and translated audio are not evaluated by this ASR/VAD experiment.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Per-utterance references and hypotheses stay in memory only; aggregate metrics are exported.
    import shutil
    shutil.rmtree(out_dir, ignore_errors=True)
    print(json.dumps({"output": str(args.output), "asr_utterances": len(asr_rows),
                      "recordings": len(selected_recordings), "model_load_ms": model_load_ms,
                      "asr_groups": asr_metrics["groups"], "vad_configurations": len(vad_results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
