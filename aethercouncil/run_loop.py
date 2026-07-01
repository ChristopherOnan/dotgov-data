"""
run_loop.py — always-on paper trading loop for AetherCouncil.

Runs trading_engine.run_cycle on an interval through the 24/5 window
(Sun 8pm -> Fri 8pm ET), respects the daily loss circuit breaker and token
budget, and writes a nightly calibration + cost report.

SAFE BY DEFAULT: decision-only (dry_run) unless you set PAPER_EXECUTE=1 with
Alpaca paper keys. Live trading still requires trading_engine's live gate.

    python3 run_loop.py --check     # is the 24/5 window open right now?
    python3 run_loop.py --once      # run exactly one cycle and exit
    python3 run_loop.py             # run forever
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from trading_engine import run_cycle, DailyRisk, TRADING_MODE

log = logging.getLogger("aethercouncil.loop")
ET = ZoneInfo("America/New_York")

INTERVAL = int(os.getenv("LOOP_INTERVAL", "60"))       # seconds between scans
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "20"))      # ET hour for nightly report
LOG_FILE = os.getenv("LOOP_LOG", "aethercouncil_loop.log")
START_EQUITY = float(os.getenv("START_EQUITY", "10000"))
PAPER_EXECUTE = os.getenv("PAPER_EXECUTE") == "1"


def in_trading_window(now: datetime | None = None) -> bool:
    """Alpaca 24/5: Sunday 20:00 ET through Friday 20:00 ET."""
    now = (now or datetime.now(ET)).astimezone(ET)
    wd = now.weekday()             # Mon=0 .. Sun=6
    if wd == 5:                    # Saturday: closed
        return False
    if wd == 6:                    # Sunday: opens 20:00 ET
        return now.hour >= 20
    if wd == 4:                    # Friday: closes 20:00 ET
        return now.hour < 20
    return True                    # Mon–Thu: open


def _classify(change_pct: float, rsi: float) -> tuple[str, str]:
    """Plain-English green/red/wait call from price move + RSI."""
    if rsi < 30 and change_pct < 0:
        return "RED", "oversold & falling — knife, avoid"
    if change_pct <= -3.0:
        return "RED", "falling hard — exit / stay out"
    if change_pct >= 2.0 and 45 <= rsi <= 70:
        return "GREEN", "uptrend with room — buy setup"
    if rsi > 72:
        return "WAIT", "overbought — let it cool"
    if rsi < 35 and change_pct >= 0:
        return "GREEN", "bouncing off oversold — watch entry"
    return "WAIT", "neutral — no edge yet"


_DOT = {"GREEN": "🟢", "RED": "🔴", "WAIT": "🟡"}


def _build_green_red_board(limit: int = 20) -> str:
    """Build simple green/red board: real prices, RSI, one-line reason."""
    try:
        from market_data import get_quotes
        from stream_indicators import LiveTA
        from bars import get_bars
        from universe import get_universe

        symbols = get_universe()[:limit]
        quotes = get_quotes(symbols)
        rows = []
        for sym in symbols:
            try:
                q = quotes.get(sym)
                if not q or q.price is None:
                    continue
                price = q.price
                change_pct = q.change_pct or 0.0
                # RSI from daily bars via a fresh engine per symbol (no state bleed)
                rsi = 50.0
                bars = get_bars(sym, limit=60)
                if bars and len(bars) > 15:
                    ta = LiveTA()
                    for b in bars:
                        ta.update(b["c"], b.get("v", 0))
                    if ta.rsi.value is not None:
                        rsi = ta.rsi.value
                color, reason = _classify(change_pct, rsi)
                rows.append((color, sym, price, change_pct, rsi, reason))
            except Exception:  # noqa: BLE001 - one bad symbol shouldn't kill the board
                continue
        if not rows:
            return "(no data — market feed unreachable)"
        # sort GREEN first, then WAIT, then RED
        order = {"GREEN": 0, "WAIT": 1, "RED": 2}
        rows.sort(key=lambda r: (order[r[0]], -r[3]))
        lines = [
            f"{_DOT[c]} {c:5} {s:6} ${p:8.2f}  {ch:+5.1f}%  RSI {rsi:4.0f}  {why}"
            for c, s, p, ch, rsi, why in rows
        ]
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"(board unavailable: {e})"


def nightly_report(tokens_today: float) -> str:
    board = _build_green_red_board()
    text = (f"\n=== AETHER COUNCIL BOARD {datetime.now(ET):%a, %b %d %H:%M ET} ===\n"
            f"mode={TRADING_MODE}  tokens_spent_today=${tokens_today:.4f}\n\n"
            f"{board}\n"
            f"\n(🟢 GREEN: buy setups  🔴 RED: avoid/exit  🟡 WAIT: hold)\n")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(text + "\n")
    except Exception:  # noqa: BLE001
        pass
    return text


async def one_cycle(risk: DailyRisk) -> dict:
    halted, why = risk.trading_halted()
    if halted:
        log.info("trading halted: %s", why)
        return {"halted": why}
    out = await run_cycle(dry_run=not PAPER_EXECUTE)
    for d in out.get("decisions", []):
        risk.tokens_spent += d.get("cost_usd") or 0.0
    log.info("cycle: %d setups, %d decisions, tokens today $%.4f",
             len(out.get("setups", [])), len(out.get("decisions", [])),
             risk.tokens_spent)
    return out


async def main() -> None:
    risk = DailyRisk(START_EQUITY)
    last_report = None
    log.info("loop start: mode=%s execute=%s interval=%ds", TRADING_MODE,
             PAPER_EXECUTE, INTERVAL)
    while True:
        now = datetime.now(ET)
        if now.hour == REPORT_HOUR and last_report != now.date():
            print(nightly_report(risk.tokens_spent))
            last_report = now.date()
        if in_trading_window(now):
            try:
                await one_cycle(risk)
            except Exception as e:  # noqa: BLE001 - never let the loop die
                log.error("cycle error: %s", e, exc_info=True)
        else:
            log.info("outside 24/5 window (%s ET) — idle", now.strftime("%a %H:%M"))
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if "--check" in sys.argv:
        now = datetime.now(ET)
        print(f"now={now:%a %Y-%m-%d %H:%M ET}  window_open={in_trading_window(now)}")
    elif "--once" in sys.argv:
        print(asyncio.run(one_cycle(DailyRisk(START_EQUITY))))
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\nloop stopped.")
