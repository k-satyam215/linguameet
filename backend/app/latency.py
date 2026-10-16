"""Latency instrumentation. Latency is a first-class metric, not an afterthought."""
from __future__ import annotations

from collections import defaultdict, deque


class Metrics:
    """Rolling per-stage latency samples (milliseconds) with p50/p95 summaries."""

    def __init__(self, window: int = 500) -> None:
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self.counters: dict[str, int] = defaultdict(int)

    def record(self, stage: str, ms: float) -> None:
        self._samples[stage].append(float(ms))

    def incr(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    @staticmethod
    def _pct(sorted_vals: list[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        k = (len(sorted_vals) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(sorted_vals) - 1)
        frac = k - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    def summary(self) -> dict:
        stages = {}
        for name, dq in self._samples.items():
            vals = sorted(dq)
            stages[name] = {
                "count": len(vals),
                "p50_ms": round(self._pct(vals, 0.50), 1),
                "p95_ms": round(self._pct(vals, 0.95), 1),
                "max_ms": round(vals[-1], 1) if vals else 0.0,
            }
        return {"stages": stages, "counters": dict(self.counters)}
