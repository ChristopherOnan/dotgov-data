"""
market_context.py — build a MARKET CONTEXT block to inject into agent prompts.

This is the fix for "shallow, quick answers": prepend real numbers to every
agent's input so Claude / Grok / Gemini reason over ground truth instead of
stale memory.

Integration (one line per agent). In each agent's build-prompt path:

    from market_context import build_market_context
    ctx = build_market_context(tickers)          # sync; fast
    messages.insert(0, {"role": "system", "content": ctx})

If you're in async code and want to be safe about the network call:

    import asyncio
    ctx = await asyncio.to_thread(build_market_context, tickers)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_data import get_quotes

_ET = ZoneInfo("America/New_York")


def market_is_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(_ET)).astimezone(_ET)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60  # 09:30–16:00 ET (ignores holidays)


def build_market_context(tickers: list[str]) -> str:
    now = datetime.now(_ET)
    quotes = get_quotes(tickers)
    state = "OPEN (RTH)" if market_is_open(now) else "CLOSED / off-hours"

    lines = [
        "=== MARKET CONTEXT ===",
        f"As of {now.strftime('%Y-%m-%d %H:%M')} ET — market {state}.",
        "Use these live numbers as ground truth. Do not invent prices.",
        "",
    ]
    src = "unavailable"
    def r(x):  # tidy floats for the prompt
        return f"{x:.2f}" if isinstance(x, (int, float)) else x
    for sym, q in quotes.items():
        if q.price is None:
            lines.append(f"  {sym:6} — quote unavailable")
            continue
        src = q.source
        chg = f"{q.change_pct:+.2f}%" if q.change_pct is not None else "n/a"
        extras = []
        if q.open is not None:  extras.append(f"O {r(q.open)}")
        if q.high is not None:  extras.append(f"H {r(q.high)}")
        if q.low is not None:   extras.append(f"L {r(q.low)}")
        if q.volume:            extras.append(f"vol {int(q.volume):,}")
        lines.append(f"  {sym:6} ${r(q.price)}  ({chg})  " + "  ".join(extras))
    lines.append("")
    lines.append(f"(data source: {src})")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(build_market_context(sys.argv[1:] or ["ASTS", "RKLB", "ACHR"]))
