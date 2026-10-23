"""Score exported predictions without contacting any model provider.

Usage: python -m scripts.evaluate predictions.jsonl --output metrics.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.evaluation import score_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path, help="JSONL prediction export (UTF-8)")
    parser.add_argument("--output", type=Path, help="write JSON report here (default: stdout)")
    parser.add_argument("--require-paired", action="store_true", help="fail if model systems do not cover identical utterance IDs per task/language")
    args = parser.parse_args()

    rows = []
    with args.jsonl.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                parser.error(f"{args.jsonl}:{line_number}: invalid JSON: {exc}")
    try:
        report = score_rows(rows)
    except ValueError as exc:
        parser.error(str(exc))

    ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        ids[(str(row["task"]), str(row["language"]), str(row["model"]))].add(str(row["id"]))
    pair_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for task, language, model in ids:
        pair_groups[(task, language)].append(model)
    pairing = []
    for (task, language), models in sorted(pair_groups.items()):
        models = sorted(models)
        all_ids = [ids[(task, language, model)] for model in models]
        common = set.intersection(*all_ids) if all_ids else set()
        union = set.union(*all_ids) if all_ids else set()
        item = {"task": task, "language": language, "models": models, "paired_utterances": len(common), "union_utterances": len(union)}
        pairing.append(item)
        if args.require_paired and any(model_ids != common for model_ids in all_ids):
            parser.error(f"unpaired utterance IDs for {task}/{language}: model outputs must cover the same IDs")
    report["pairing"] = pairing
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
