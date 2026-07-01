"""
backtest.py — validate the RSI/VWAP signal rules on history BEFORE paper.

Replays historical bars through the SAME LiveTA engine the live loop uses, so
what you test is exactly what you'll trade. Simulates simple long trades:
enter on a 'buy' signal, exit on a 'sell' signal, an ATR stop, or a max hold.
Reports win rate, avg return, and total return with a modeled cost per trade.

    python3 backtest.py RKLB ASTS NVDA --tf 1h --stop 1.5 --hold 8

No keys needed (Yahoo bars). This tells you if the rules have any edge at all.
"""

from __future__ import annotations

import argparse
import logging
from statistics import mean

from bars import atr, get_bars
from stream_indicators import LiveTA

log = logging.getLogger("aethercouncil.backtest")

COST_PER_TRADE = 0.0005  # 5 bps round-trip slippage/fees assumption


def backtest(symbol: str, timeframe: str = "1h", limit: int = 300,
             stop_mult: float = 1.5, max_hold: int = 8,
             oversold: float = 30.0, overbought: float = 70.0) -> dict:
    bars = get_bars(symbol, timeframe=timeframe, limit=limit)
    if len(bars) < 40:
        return {"symbol": symbol, "error": f"only {len(bars)} bars"}
    a = atr(bars) or (bars[-1]["c"] * 0.02)
    ta = LiveTA(oversold=oversold, overbought=overbought)
    trades: list[float] = []
    pos = None  # (entry_price, bars_held, stop)
    for b in bars:
        px = b["c"]
        sig = ta.update(px, b.get("v", 0))
        if pos:
            entry, held, stop = pos
            held += 1
            exit_now, reason = False, ""
            if px <= stop:
                exit_now, reason = True, "stop"
            elif sig.action == "sell":
                exit_now, reason = True, "signal"
            elif held >= max_hold:
                exit_now, reason = True, "time"
            if exit_now:
                ret = (px - entry) / entry - COST_PER_TRADE
                trades.append(ret)
                pos = None
            else:
                pos = (entry, held, stop)
        if pos is None and sig.action == "buy":
            pos = (px, 0, px - stop_mult * a)
    wins = [t for t in trades if t > 0]
    total = 1.0
    for t in trades:
        total *= (1 + t)
    return {
        "symbol": symbol, "bars": len(bars), "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else None,
        "avg_return": round(mean(trades), 5) if trades else None,
        "total_return_pct": round((total - 1) * 100, 2) if trades else 0.0,
    }


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", default=["RKLB", "ASTS", "NVDA"])
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--stop", type=float, default=1.5)
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--os", dest="oversold", type=float, default=30.0)
    ap.add_argument("--ob", dest="overbought", type=float, default=70.0)
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()
    syms = args.symbols or ["RKLB", "ASTS", "NVDA"]
    print(f"{'sym':6} {'trades':>6} {'win%':>6} {'avg%':>7} {'total%':>8}")
    agg = []
    for s in syms:
        r = backtest(s, timeframe=args.tf, limit=args.limit, stop_mult=args.stop,
                     max_hold=args.hold, oversold=args.oversold,
                     overbought=args.overbought)
        if r.get("error"):
            print(f"{s:6} {r['error']}"); continue
        wr = f"{r['win_rate']*100:.0f}" if r['win_rate'] is not None else "-"
        av = f"{r['avg_return']*100:.2f}" if r['avg_return'] is not None else "-"
        print(f"{s:6} {r['trades']:>6} {wr:>6} {av:>7} {r['total_return_pct']:>8}")
        if r['trades']:
            agg.append(r)
    if agg:
        print(f"\nportfolio avg win%={mean(x['win_rate'] for x in agg)*100:.0f}  "
              f"avg total%={mean(x['total_return_pct'] for x in agg):.2f}  "
              f"(modeled {COST_PER_TRADE*100:.2f}%/trade cost)")
        print("NOTE: intraday history is limited/free-source; treat as a smoke "
              "test of the RULES, not a promise. Paper-validate next.")


if __name__ == "__main__":
    main()
