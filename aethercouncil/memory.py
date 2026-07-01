"""
memory.py — episodic memory so the system learns from its own history.

This is the heart of self-improvement (FinMem / Reflexion): every decision is
stored with the market features that produced it and, once known, its outcome.
Before a new decision, we recall the most SIMILAR past episodes and inject them
as context — "the last 5 times we saw an oversold bounce on a semi after a gap,
here's what actually happened." The agents stop repeating losing patterns and
lean into winning ones, with no fine-tuning required.

Keyed by the calibration prediction id (pid) so portfolio resolution feeds both
calibration scoring and memory outcomes in one step.

    import memory
    pid = "abc123"
    memory.record(pid, "RKLB", {"rsi":29,"change_pct":-1.2,"setup":"oversold_bounce"}, prob=0.66)
    ctx = memory.recall("RKLB", {"rsi":31,"setup":"oversold_bounce"})   # -> prompt text
    # ...later, when the trade closes...
    memory.resolve(pid, outcome=1, ret=0.031)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("aethercouncil.memory")

MEM_PATH = os.getenv("MEMORY_PATH", "memory.jsonl")
RECALL_K = int(os.getenv("MEMORY_RECALL_K", "5"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> list[dict]:
    if not os.path.exists(MEM_PATH):
        return []
    out = []
    with open(MEM_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _write(rows: list[dict]) -> None:
    with open(MEM_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def record(pid: str, symbol: str, features: dict, prob: float, note: str = "") -> str:
    """Store a decision episode (outcome filled later by resolve())."""
    with open(MEM_PATH, "a") as f:
        f.write(json.dumps({
            "pid": pid, "ts": _now(), "symbol": symbol.upper(),
            "features": features, "prob": float(prob), "note": note,
            "outcome": None, "ret": None,
        }) + "\n")
    return pid


def resolve(pid: str, outcome: int, ret: float | None = None) -> bool:
    rows = _read()
    hit = False
    for r in rows:
        if r.get("pid") == pid and r.get("outcome") is None:
            r["outcome"] = int(outcome)
            r["ret"] = ret
            r["resolved_ts"] = _now()
            hit = True
    if hit:
        _write(rows)
    return hit


def _similarity(a: dict, b: dict, same_symbol: bool) -> float:
    """Cheap, embedding-free similarity over trading features (0..1, higher=closer)."""
    score = 0.0
    # setup-type match is the strongest signal
    if a.get("setup") and a.get("setup") == b.get("setup"):
        score += 0.5
    # RSI proximity (0..100 scale)
    if a.get("rsi") is not None and b.get("rsi") is not None:
        score += 0.3 * max(0.0, 1 - abs(a["rsi"] - b["rsi"]) / 40.0)
    # move proximity
    if a.get("change_pct") is not None and b.get("change_pct") is not None:
        score += 0.2 * max(0.0, 1 - abs(a["change_pct"] - b["change_pct"]) / 10.0)
    if same_symbol:
        score += 0.25   # same ticker's own history is extra relevant
    return score


def recall(symbol: str, features: dict, k: int = RECALL_K) -> str:
    """Return a prompt-ready block of the k most similar RESOLVED past episodes."""
    rows = [r for r in _read() if r.get("outcome") in (0, 1)]
    if not rows:
        return ""
    scored = []
    for r in rows:
        sim = _similarity(features, r.get("features", {}),
                          same_symbol=r.get("symbol") == symbol.upper())
        scored.append((sim, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [r for s, r in scored[:k] if s > 0.2]
    if not top:
        return ""
    lines = ["PAST SIMILAR SETUPS (learn from these outcomes):"]
    wins = 0
    for r in top:
        f = r.get("features", {})
        res = "WIN" if r["outcome"] == 1 else "LOSS"
        wins += r["outcome"]
        retpct = f"{r['ret']*100:+.1f}%" if r.get("ret") is not None else ""
        lines.append(f"- {r['symbol']} {f.get('setup','?')} RSI~{f.get('rsi','?')} "
                     f"(pred {r['prob']:.2f}) -> {res} {retpct}")
    lines.append(f"(similar-setup hit rate: {wins}/{len(top)})")
    return "\n".join(lines)


def stats() -> dict:
    rows = _read()
    resolved = [r for r in rows if r.get("outcome") in (0, 1)]
    wins = sum(r["outcome"] for r in resolved)
    return {"episodes": len(rows), "resolved": len(resolved),
            "wins": wins, "hit_rate": round(wins / len(resolved), 3) if resolved else None}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("memory stats:", stats())
    demo = recall("RKLB", {"rsi": 30, "setup": "oversold_bounce", "change_pct": -1.0})
    print("\n" + (demo or "(no similar episodes yet)"))
