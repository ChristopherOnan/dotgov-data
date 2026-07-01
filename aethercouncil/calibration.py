"""
calibration.py — score whether the council is actually any good.

A probability machine you can't score is faith, not edge. This logs every
probability call the council makes and computes a rolling Brier score once
outcomes are known (lower = better; 0.25 = coin-flip baseline).

Usage:
    from calibration import log_prediction, resolve_prediction, report

    pid = log_prediction("ASTS", prob=0.62, direction="up", horizon="1w")
    # ...later, when you know what happened...
    resolve_prediction(pid, outcome=1)   # 1 = it happened, 0 = it didn't
    print(report())

Zero dependencies; appends JSONL to CALIB_PATH (default ./calibration.jsonl).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

CALIB_PATH = os.getenv("CALIB_PATH", "calibration.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> list[dict]:
    if not os.path.exists(CALIB_PATH):
        return []
    out = []
    with open(CALIB_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _write(rows: list[dict]) -> None:
    with open(CALIB_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def log_prediction(ticker: str, prob: float, direction: str = "up",
                   horizon: str = "1w", note: str = "") -> str:
    """Record a probabilistic call. Returns a prediction id."""
    pid = uuid.uuid4().hex[:12]
    with open(CALIB_PATH, "a") as f:
        f.write(json.dumps({
            "id": pid, "ts": _now(), "ticker": ticker.upper(),
            "prob": float(prob), "direction": direction, "horizon": horizon,
            "note": note, "outcome": None, "resolved_ts": None,
        }) + "\n")
    return pid


def resolve_prediction(pid: str, outcome: int) -> bool:
    """Mark a prediction's outcome (1 happened / 0 did not). Returns success."""
    rows = _read()
    hit = False
    for r in rows:
        if r["id"] == pid:
            r["outcome"] = int(outcome)
            r["resolved_ts"] = _now()
            hit = True
    if hit:
        _write(rows)
    return hit


def brier_score() -> float | None:
    """Mean squared error of resolved probability calls. None if no data."""
    resolved = [r for r in _read() if r.get("outcome") in (0, 1)]
    if not resolved:
        return None
    return sum((r["prob"] - r["outcome"]) ** 2 for r in resolved) / len(resolved)


def report() -> str:
    rows = _read()
    resolved = [r for r in rows if r.get("outcome") in (0, 1)]
    bs = brier_score()
    lines = [
        "=== CALIBRATION REPORT ===",
        f"predictions logged : {len(rows)}",
        f"resolved           : {len(resolved)}",
        f"Brier score        : {bs:.4f}" if bs is not None else "Brier score        : n/a",
        "  (0.00 perfect · 0.25 coin-flip · lower is better)",
    ]
    if resolved:
        hits = sum(1 for r in resolved
                   if (r["prob"] >= 0.5) == bool(r["outcome"]))
        lines.append(f"directional accuracy: {hits}/{len(resolved)} "
                     f"({hits/len(resolved)*100:.0f}%)")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
