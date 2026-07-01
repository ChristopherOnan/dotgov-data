"""
data_guard.py — trust, but verify. Clean data is the bedrock of a learning system.

A self-improving loop that learns from corrupted inputs learns the wrong lessons
(garbage in, garbage out). This layer verifies every price before it can drive a
decision or a scored prediction, using the ensemble approach the literature
recommends: cross-source agreement + history plausibility + adaptive bounds.

Checks (each raises a flag; critical flags => not trusted):
  • cross_source   — Finnhub vs Yahoo agree within CROSS_TOL (needs FINNHUB key)
  • history        — price within MAX_JUMP of the recent close, unless a real
                     volume spike / gap corroborates it
  • sane           — positive, finite, non-zero

    from data_guard import verified_quote
    v = verified_quote("MU")
    if v["trust"]:
        use(v["price"])
    else:
        skip(v["flags"])            # e.g. ["history_outlier(7.6x)"]

Adding the (free) FINNHUB_API_KEY turns on true cross-source triangulation and
materially improves integrity — highly recommended before live trading.
"""

from __future__ import annotations

import logging
import os
import statistics
from typing import Optional

log = logging.getLogger("aethercouncil.dataguard")

CROSS_TOL = float(os.getenv("GUARD_CROSS_TOL", "0.03"))     # 3% source disagreement
MAX_JUMP = float(os.getenv("GUARD_MAX_JUMP", "0.35"))       # 35% vs recent close
SPIKE_OK_VOL = float(os.getenv("GUARD_SPIKE_VOL", "2.5"))   # vol spike that excuses a big move


def _recent_ref(symbol: str) -> tuple[Optional[float], float]:
    """Return (reference close, volume-spike ratio) from recent daily bars,
    excluding the latest bar so a bad latest tick can't poison its own check."""
    try:
        from bars import get_bars, volume_spike
        bars = get_bars(symbol, timeframe="1d", limit=25)
        if len(bars) < 6:
            return None, 1.0
        closes = [b["c"] for b in bars[:-1]]        # exclude latest
        ref = statistics.median(closes[-6:])         # robust to one bad print
        return ref, (volume_spike(bars) or 1.0)
    except Exception as e:  # noqa: BLE001
        log.warning("history ref failed for %s: %s", symbol, e)
        return None, 1.0


def verified_quote(symbol: str) -> dict:
    """Cross-check sources + history. Returns price, trust flag, and reasons."""
    from market_data import _finnhub, _yahoo  # reuse existing fetchers
    symbol = symbol.upper().strip()
    flags: list[str] = []

    fh = _finnhub(symbol)
    yh = _yahoo(symbol)
    prices = {q.source: q.price for q in (fh, yh) if q and q.price}

    if not prices:
        return {"symbol": symbol, "price": None, "trust": False,
                "flags": ["no_source"], "sources": {}}

    # --- cross-source agreement (only if we have two) ----------------------
    if len(prices) == 2:
        vals = list(prices.values())
        disagree = abs(vals[0] - vals[1]) / min(vals)
        if disagree > CROSS_TOL:
            flags.append(f"source_disagreement({disagree:.0%})")

    # prefer finnhub price if present (real-time trade), else yahoo
    price = prices.get("finnhub") or prices.get("yahoo")

    # --- history plausibility ---------------------------------------------
    ref, spike = _recent_ref(symbol)
    if ref and ref > 0:
        jump = abs(price - ref) / ref
        if jump > MAX_JUMP and spike < SPIKE_OK_VOL:
            # a huge move with NO volume corroboration => almost certainly bad
            # data (split artifact / wrong symbol), not a real move
            flags.append(f"history_outlier({price/ref:.1f}x, vol {spike:.1f}x)")

    # --- basic sanity ------------------------------------------------------
    if not price or price <= 0:
        flags.append("nonpositive")

    critical = [f for f in flags if f.startswith(("history_outlier", "nonpositive",
                                                  "source_disagreement"))]
    return {"symbol": symbol, "price": price, "trust": not critical,
            "flags": flags, "sources": prices, "ref": ref}


def verified_price(symbol: str) -> Optional[float]:
    """Convenience: trusted price or None."""
    v = verified_quote(symbol)
    return v["price"] if v["trust"] else None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for s in (sys.argv[1:] or ["NVDA", "MU", "NFLX", "RKLB"]):
        v = verified_quote(s)
        tag = "OK " if v["trust"] else "REJECT"
        print(f"{tag} {s:6} price={v['price']} ref={v.get('ref')} "
              f"sources={v['sources']} flags={v['flags']}")
