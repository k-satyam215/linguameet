"""Corpus-level metrics for reproducible speech and translation experiments."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    """Levenshtein distance in O(min(n, m)) memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for i, ref_token in enumerate(reference, start=1):
        current = [i]
        for j, hyp_token in enumerate(hypothesis, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ref_token != hyp_token)))
        previous = current
    return previous[-1]


def _ngrams(tokens: list[str], size: int) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    for i in range(max(0, len(tokens) - size + 1)):
        counts[tuple(tokens[i:i + size])] += 1
    return counts


def _fscore(matches: int, predicted: int, reference: int, beta: float = 1.0) -> float:
    if not predicted or not reference:
        return 0.0
    precision, recall = matches / predicted, matches / reference
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall) if precision or recall else 0.0


def sentence_bleu(reference: str, hypothesis: str, max_order: int = 4) -> float:
    """Add-one-smoothed sentence BLEU, on the 0..100 scale."""
    ref, hyp = _tokens(reference), _tokens(hypothesis)
    if not hyp:
        return 0.0
    log_precision = 0.0
    for order in range(1, max_order + 1):
        rc, hc = _ngrams(ref, order), _ngrams(hyp, order)
        total = sum(hc.values())
        clipped = sum(min(count, rc[gram]) for gram, count in hc.items())
        log_precision += math.log((clipped + 1) / (total + 1)) / max_order
    return 100 * math.exp(min(0.0, 1 - len(ref) / len(hyp)) + log_precision)


def sentence_chrf(reference: str, hypothesis: str, max_order: int = 6, beta: float = 2.0) -> float:
    """Whitespace-normalized character n-gram F-beta, on the 0..100 scale."""
    ref = " ".join(reference.casefold().split())
    hyp = " ".join(hypothesis.casefold().split())
    if not ref or not hyp:
        return 0.0
    scores = []
    for order in range(1, max_order + 1):
        rc, hc = _ngrams(list(ref), order), _ngrams(list(hyp), order)
        matches = sum(min(count, rc[gram]) for gram, count in hc.items())
        scores.append(_fscore(matches, sum(hc.values()), sum(rc.values()), beta))
    return 100 * sum(scores) / len(scores)


def percentile(values: Iterable[float], p: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def score_rows(rows: list[dict]) -> dict:
    """Score records grouped by model/task/language.

    Required: id, model, task (asr|translation), language, reference, hypothesis.
    Optional timings_ms maps stage names to nonnegative millisecond values.
    """
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        required = ("id", "model", "task", "language", "reference", "hypothesis")
        missing = [key for key in required if key not in row]
        if missing:
            raise ValueError(f"row is missing required fields: {', '.join(missing)}")
        if row["task"] not in {"asr", "translation"}:
            raise ValueError("task must be 'asr' or 'translation'")
        group = (str(row["model"]), str(row["task"]), str(row["language"]))
        unique = (group[0], group[1], str(row["id"]))
        if unique in seen:
            raise ValueError(f"duplicate utterance id for model/task: {row['id']}")
        seen.add(unique)
        groups[group].append(row)

    results = []
    for (model, task, language), items in sorted(groups.items()):
        ref_words = hyp_words = word_errors = 0
        ref_chars = char_errors = 0
        bleu, chrf = [], []
        latency: dict[str, list[float]] = defaultdict(list)
        for item in items:
            reference, hypothesis = str(item["reference"]), str(item["hypothesis"])
            rw, hw = _tokens(reference), _tokens(hypothesis)
            rc, hc = list(reference.casefold()), list(hypothesis.casefold())
            word_errors += edit_distance(rw, hw)
            char_errors += edit_distance(rc, hc)
            ref_words += len(rw)
            hyp_words += len(hw)
            ref_chars += len(rc)
            if task == "translation":
                bleu.append(sentence_bleu(reference, hypothesis))
                chrf.append(sentence_chrf(reference, hypothesis))
            for stage, value in (item.get("timings_ms") or {}).items():
                if isinstance(value, (int, float)) and value >= 0:
                    latency[str(stage)].append(float(value))
        results.append({
            "model": model, "task": task, "language": language, "utterances": len(items),
            "wer": word_errors / ref_words if ref_words else None,
            "cer": char_errors / ref_chars if ref_chars else None,
            "hypothesis_tokens_per_reference_token": hyp_words / ref_words if ref_words else None,
            "mean_sentence_bleu": sum(bleu) / len(bleu) if bleu else None,
            "mean_sentence_chrf": sum(chrf) / len(chrf) if chrf else None,
            "latency_ms": {
                stage: {"count": len(values), "p50": round(percentile(values, .50), 1), "p95": round(percentile(values, .95), 1)}
                for stage, values in sorted(latency.items())
            },
        })
    return {"schema_version": 1, "groups": results}
