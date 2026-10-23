"""Generate paired IndicTrans2 predictions from a local AI4Bharat checkout.

Input JSONL fields: id, source_text, source_language, target_language, reference.
The model inference call follows AI4Bharat's published `Model.batch_translate` API.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

LANG_CODES = {
    "en": "eng_Latn", "hi": "hin_Deva", "bn": "ben_Beng",
    "ta": "tam_Taml", "te": "tel_Telu", "mr": "mar_Deva",
}


def predict_rows(rows: list[dict], model: Any, system_name: str = "indictrans2-ct2") -> list[dict]:
    predictions = []
    for row in rows:
        try:
            source_lang = LANG_CODES[row["source_language"]]
            target_lang = LANG_CODES[row["target_language"]]
            source_text = row["source_text"]
            reference = row["reference"]
            utterance_id = row["id"]
        except KeyError as exc:
            raise ValueError(f"missing or unsupported input field/language: {exc.args[0]}") from exc
        started = time.perf_counter()
        translated = model.batch_translate([source_text], source_lang, target_lang)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        hypothesis = translated[0] if isinstance(translated, (list, tuple)) and translated else translated
        if not isinstance(hypothesis, str) or not hypothesis.strip():
            raise ValueError(f"model returned no translation for id={utterance_id}")
        predictions.append({
            "id": utterance_id, "model": system_name, "task": "translation",
            "language": row["target_language"], "reference": reference,
            "hypothesis": hypothesis.strip(), "timings_ms": {"translation_model": elapsed_ms},
        })
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL with paired references and language codes")
    parser.add_argument("--repo", type=Path, required=True, help="local AI4Bharat/IndicTrans2 checkout")
    parser.add_argument("--checkpoint", type=Path, required=True, help="downloaded IndicTrans2 checkpoint")
    parser.add_argument("--model-type", choices=("ctranslate2", "fairseq"), default="ctranslate2")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--system-name", default="indictrans2-ct2")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (args.repo / "inference" / "engine.py").is_file():
        parser.error("--repo must point to IndicTrans2 checkout containing inference/engine.py")
    if not args.checkpoint.is_dir():
        parser.error("--checkpoint directory does not exist")
    sys.path.insert(0, str(args.repo.resolve()))
    try:
        from inference.engine import Model
    except ImportError as exc:
        parser.error(f"IndicTrans2 dependencies are missing from this Python environment: {exc}")
    try:
        rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        parser.error(f"invalid input JSONL: {exc}")
    load_started = time.perf_counter()
    model = Model(str(args.checkpoint), device=args.device, model_type=args.model_type)
    model_load_ms = round((time.perf_counter() - load_started) * 1000, 1)
    try:
        predictions = predict_rows(rows, model, args.system_name)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions), encoding="utf-8")
    print(json.dumps({"predictions": len(predictions), "model_load_ms": model_load_ms, "model": args.system_name}))


if __name__ == "__main__":
    main()
