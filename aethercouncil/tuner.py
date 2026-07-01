"""
tuner.py — self-tuning strategy parameters, with an anti-overfitting gate.

Markets drift, so the best RSI thresholds / stop distance last month may not be
best next month. This periodically re-searches the parameter grid on RECENT data
— but the cardinal sin of tuning is overfitting, so nothing is adopted unless it
proves out ON DATA IT WASN'T TUNED ON.

Method:
  1. For each tune symbol, fetch bars and split TRAIN (older 70%) / VALID (newer 30%).
  2. Grid-search params on TRAIN, ranking by a t-stat-like score
     (mean_return * sqrt(n_trades)) so a lucky single trade can't win.
  3. Take the top candidates and re-measure them on the held-out VALID window.
  4. ADOPT the best only if it (a) beats the CURRENT params out of sample,
     (b) is positive out of sample, and (c) has enough validation trades.
     Otherwise keep what we have. Overfit settings die at the validation gate.

Adopted params are written to params.json (read live via params.py). Bounded,
logged, reversible.

    python3 tuner.py                 # tune now, print the decision
    python3 tuner.py --symbols NVDA AMD RKLB
"""

from __future__ import annotations

import argparse
import itertools
import logging
import math
import os
from statistics import mean

from backtest import simulate
from bars import atr, get_bars
import params

log = logging.getLogger("aethercouncil.tuner")

# search grid (kept modest — a smaller grid overfits less and runs faster)
GRID = {
    "oversold":   [25.0, 30.0, 35.0, 40.0],
    "overbought": [60.0, 65.0, 70.0],
    "stop_mult":  [1.0, 1.5, 2.0, 2.5],
    "max_hold":   [3, 5, 8],
}

# Hourly bars give ~10x the signal of free daily history, so tuning has enough
# trades to be meaningful (daily Yahoo caps at ~60 bars/symbol).
TUNE_TIMEFRAME = os.getenv("TUNE_TIMEFRAME", "1h")
TRAIN_FRAC = float(os.getenv("TUNE_TRAIN_FRAC", "0.70"))
BAR_LIMIT = int(os.getenv("TUNE_BAR_LIMIT", "700"))
MIN_TRAIN_TRADES = int(os.getenv("TUNE_MIN_TRAIN_TRADES", "12"))
MIN_VALID_TRADES = int(os.getenv("TUNE_MIN_VALID_TRADES", "5"))
TOP_K = int(os.getenv("TUNE_TOP_K", "8"))
DEFAULT_SYMBOLS = os.getenv(
    "TUNE_SYMBOLS",
    "NVDA,AMD,RKLB,ASTS,TSLA,PLTR,MU,AVGO,ARM,SMCI,META,AMZN"
).split(",")


def _score(returns: list[float]) -> float:
    """t-stat-like: rewards positive expectancy scaled by sample size."""
    if len(returns) < 2:
        return float("-inf")
    m = mean(returns)
    return m * math.sqrt(len(returns))


def _pool(symbol_bars: dict, combo: dict, phase: str) -> list[float]:
    """Aggregate trade returns across all symbols for a param combo, split
    per-symbol (each symbol has a different bar count) into train/valid."""
    pool: list[float] = []
    for sym, (bars, a) in symbol_bars.items():
        cut = int(len(bars) * TRAIN_FRAC)
        seg = bars[:cut] if phase == "train" else bars[cut:]
        if len(seg) < 20:
            continue
        r = simulate(seg, stop_mult=combo["stop_mult"], max_hold=combo["max_hold"],
                     oversold=combo["oversold"], overbought=combo["overbought"],
                     atr_val=a)
        pool.extend(r["returns"])
    return pool


def _agg(returns: list[float]) -> dict:
    if not returns:
        return {"trades": 0, "total_return_pct": 0.0, "win_rate": None, "score": float("-inf")}
    total = 1.0
    for t in returns:
        total *= (1 + t)
    wins = sum(1 for t in returns if t > 0)
    return {"trades": len(returns),
            "total_return_pct": round((total - 1) * 100, 2),
            "win_rate": round(wins / len(returns), 3),
            "score": round(_score(returns), 5)}


def tune(symbols: list[str] | None = None) -> dict:
    symbols = symbols or DEFAULT_SYMBOLS
    # fetch once per symbol; precompute ATR on the train portion only
    symbol_bars: dict = {}
    for s in symbols:
        try:
            bars = get_bars(s.strip(), timeframe=TUNE_TIMEFRAME, limit=BAR_LIMIT)
        except Exception as e:  # noqa: BLE001
            log.warning("skip %s: %s", s, e)
            continue
        if len(bars) < 60:
            continue
        cut = int(len(bars) * TRAIN_FRAC)
        a = atr(bars[:cut]) or (bars[cut - 1]["c"] * 0.02)
        symbol_bars[s.strip()] = (bars, a)
    if not symbol_bars:
        return {"error": "no usable bars for any tune symbol"}

    avg_bars = sum(len(b) for b, _ in symbol_bars.values()) // len(symbol_bars)
    cut = int(avg_bars * TRAIN_FRAC)

    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    ranked = []
    for c in combos:
        tr = _agg(_pool(symbol_bars, c, "train"))
        if tr["trades"] >= MIN_TRAIN_TRADES:
            ranked.append((tr["score"], c, tr))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked:
        return {"error": "no combo met the minimum training-trade floor",
                "symbols": list(symbol_bars)}

    # out-of-sample validation of the top-K training candidates
    candidates = []
    for _, c, tr in ranked[:TOP_K]:
        va = _agg(_pool(symbol_bars, c, "valid"))
        candidates.append((c, tr, va))
    candidates.sort(key=lambda x: x[2]["score"], reverse=True)

    # baseline: CURRENT params, measured on the same validation window
    cur = {"oversold": float(params.P("oversold")), "overbought": float(params.P("overbought")),
           "stop_mult": float(params.P("stop_mult")), "max_hold": int(params.P("max_hold"))}
    cur_val = _agg(_pool(symbol_bars, cur, "valid"))

    best_c, best_tr, best_va = candidates[0]
    adopt = (
        best_va["score"] > cur_val["score"]
        and best_va["total_return_pct"] > 0
        and best_va["trades"] >= MIN_VALID_TRADES
    )
    decision = {
        "symbols": list(symbol_bars), "train_bars": cut, "valid_bars": avg_bars - cut,
        "current": {**cur, "valid": cur_val},
        "best": {**best_c, "train": best_tr, "valid": best_va},
        "adopted": adopt,
    }
    if adopt:
        params.save(best_c, meta={"validated_return_pct": best_va["total_return_pct"],
                                  "valid_trades": best_va["trades"],
                                  "beat_current_by": round(best_va["score"] - cur_val["score"], 5)})
        log.info("ADOPTED new params %s (OOS +%.2f%%, %d trades)",
                 best_c, best_va["total_return_pct"], best_va["trades"])
    else:
        log.info("kept current params (best candidate didn't clear the OOS gate)")
    return decision


def _fmt(d: dict) -> str:
    if d.get("error"):
        return f"tune failed: {d['error']}"
    b, c = d["best"], d["current"]
    lines = [
        f"=== PARAMETER TUNE ({len(d['symbols'])} symbols, "
        f"{d['train_bars']} train / {d['valid_bars']} valid bars) ===",
        f"current : os={c['oversold']} ob={c['overbought']} stop={c['stop_mult']} "
        f"hold={c['max_hold']}  -> OOS {c['valid']['total_return_pct']}% "
        f"({c['valid']['trades']} trades)",
        f"best    : os={b['oversold']} ob={b['overbought']} stop={b['stop_mult']} "
        f"hold={b['max_hold']}",
        f"          train {b['train']['total_return_pct']}% ({b['train']['trades']} tr) | "
        f"OOS {b['valid']['total_return_pct']}% ({b['valid']['trades']} tr, "
        f"win {b['valid']['win_rate']})",
        f"DECISION: {'✅ ADOPTED (beat current out of sample)' if d['adopted'] else '🔒 kept current (no OOS improvement)'}",
    ]
    return "\n".join(lines)


def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    args = ap.parse_args()
    print(_fmt(tune(args.symbols)))


if __name__ == "__main__":
    _cli()
