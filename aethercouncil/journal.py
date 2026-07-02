"""
journal.py — the council's shared blackboard (structured global state).

TradingAgents' key communication insight: agents passing long chat histories
degrade ("telephone effect"). Instead, keep a STRUCTURED shared state that every
deliberation reads directly. This journal records each decision the system makes
(symbol, action, prob, reason, cost) and exposes recent() — a compact block
injected into every deliberation so all agents share the same operating picture:
what we just did, what we declined, and what we're already holding.

    import journal
    journal.log_entry("NVDA", "enter_long", 0.71, "gap +4% momo", 0.002)
    print(journal.recent())   # -> prompt-ready block
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("aethercouncil.journal")

JOURNAL_PATH = os.getenv("JOURNAL_PATH", "journal.jsonl")
RECENT_N = int(os.getenv("JOURNAL_RECENT_N", "8"))
MAX_LINES = 2000   # rotate: keep the file bounded


def log_entry(symbol: str, action: str, prob: float | None, reason: str = "",
              cost: float | None = None) -> None:
    try:
        with open(JOURNAL_PATH, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol.upper(), "action": action,
                "prob": round(prob, 3) if prob is not None else None,
                "reason": reason[:120], "cost": cost,
            }) + "\n")
        _rotate()
    except Exception as e:  # noqa: BLE001
        log.warning("journal write failed: %s", e)


def _read() -> list[dict]:
    if not os.path.exists(JOURNAL_PATH):
        return []
    out = []
    with open(JOURNAL_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _rotate() -> None:
    rows = _read()
    if len(rows) > MAX_LINES:
        with open(JOURNAL_PATH, "w") as f:
            for r in rows[-MAX_LINES // 2:]:
                f.write(json.dumps(r) + "\n")


def recent(n: int = RECENT_N) -> str:
    """Prompt-ready shared state: recent decisions + current open positions."""
    parts = []
    rows = _read()[-n:]
    if rows:
        lines = ["RECENT COUNCIL DECISIONS (shared state — don't contradict without reason):"]
        for r in rows:
            p = f" p={r['prob']}" if r.get("prob") is not None else ""
            lines.append(f"- {r['ts'][11:16]}Z {r['symbol']} {r['action']}{p} ({r.get('reason','')})")
        parts.append("\n".join(lines))
    try:
        from portfolio import Portfolio
        opens = Portfolio().open_positions()
        if opens:
            parts.append("OPEN POSITIONS: " + ", ".join(
                f"{p.symbol}({p.side} {p.qty}@{p.entry})" for p in opens))
    except Exception:  # noqa: BLE001
        pass
    return "\n\n".join(parts)


if __name__ == "__main__":
    print(recent() or "(journal empty)")
