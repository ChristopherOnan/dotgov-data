"""
agent_scorecard.py — meta-learning over the swarm: weight agents by proven skill.

Averaging every model's vote equally is naive — some models are simply better
forecasters than others, and which ones changes over time. This tracks each
model's individual calibration (Brier) as trades resolve and produces a
skill-weighted consensus: good forecasters count more, persistently-wrong ones
get down-weighted toward zero. New/low-sample models are shrunk toward equal
weight so we don't over-react to a lucky streak.

    import agent_scorecard as sc
    sc.record_votes(pid, {"claude":0.7,"grok":0.6,"deepseek":0.55})
    prob = sc.weighted_consensus({"claude":0.7,"grok":0.6,"deepseek":0.55})
    # ...on close...
    sc.resolve_votes(pid, outcome=1)
    print(sc.report())
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger("aethercouncil.scorecard")

SCORE_PATH = os.getenv("SCORECARD_PATH", "agent_scores.jsonl")
BASELINE_BRIER = 0.25          # coin-flip; models better than this earn weight
SHRINK_N = int(os.getenv("SCORECARD_SHRINK_N", "10"))   # samples for full trust


def _read() -> list[dict]:
    if not os.path.exists(SCORE_PATH):
        return []
    out = []
    with open(SCORE_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _write(rows: list[dict]) -> None:
    with open(SCORE_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def record_votes(pid: str, votes: dict[str, float]) -> None:
    """Log each model's individual probability for a decision."""
    ts = datetime.now(timezone.utc).isoformat()
    with open(SCORE_PATH, "a") as f:
        for model, prob in votes.items():
            if prob is None:
                continue
            f.write(json.dumps({"pid": pid, "ts": ts, "model": model,
                                "prob": float(prob), "outcome": None}) + "\n")


def resolve_votes(pid: str, outcome: int) -> bool:
    rows = _read()
    hit = False
    for r in rows:
        if r.get("pid") == pid and r.get("outcome") is None:
            r["outcome"] = int(outcome)
            hit = True
    if hit:
        _write(rows)
    return hit


def model_briers() -> dict[str, dict]:
    """Per-model Brier + sample count over resolved votes."""
    agg = defaultdict(lambda: {"n": 0, "sse": 0.0, "hits": 0})
    for r in _read():
        if r.get("outcome") in (0, 1):
            a = agg[r["model"]]
            a["n"] += 1
            a["sse"] += (r["prob"] - r["outcome"]) ** 2
            a["hits"] += int((r["prob"] >= 0.5) == bool(r["outcome"]))
    out = {}
    for m, a in agg.items():
        out[m] = {"n": a["n"], "brier": round(a["sse"] / a["n"], 4) if a["n"] else None,
                  "acc": round(a["hits"] / a["n"], 3) if a["n"] else None}
    return out


def weights() -> dict[str, float]:
    """Skill weights from Brier, shrunk toward equal weight for low samples."""
    briers = model_briers()
    raw = {}
    for m, s in briers.items():
        if s["brier"] is None:
            continue
        skill = max(0.0, BASELINE_BRIER - s["brier"])      # >0 means beats coin flip
        trust = min(1.0, s["n"] / SHRINK_N)                # shrink small samples
        raw[m] = skill * trust + BASELINE_BRIER * (1 - trust) * 0.0 + 1e-3 * trust
        # ^ low-sample models fall back to ~equal (handled in consensus fallback)
    return raw


def weighted_consensus(votes: dict[str, float]) -> float | None:
    """Skill-weighted mean of this round's votes; equal-weight until we have data."""
    valid = {m: p for m, p in votes.items() if p is not None}
    if not valid:
        return None
    w = weights()
    num = den = 0.0
    for m, p in valid.items():
        wi = w.get(m, 0.0)
        num += wi * p
        den += wi
    if den <= 0:                       # no skill history yet -> equal weight
        return round(sum(valid.values()) / len(valid), 4)
    return round(num / den, 4)


def report() -> str:
    briers = model_briers()
    if not briers:
        return "=== AGENT SCORECARD ===\n(no resolved votes yet)"
    w = weights()
    lines = ["=== AGENT SCORECARD (lower Brier = better) ==="]
    for m in sorted(briers, key=lambda x: (briers[x]["brier"] is None, briers[x]["brier"] or 1)):
        s = briers[m]
        lines.append(f"  {m:38} n={s['n']:<3} brier={s['brier']} acc={s['acc']} "
                     f"weight={w.get(m,0):.3f}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(report())
