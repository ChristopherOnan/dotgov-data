"""
bars.py — OHLCV bars + real volatility (ATR) and volume stats.

Gives trading_engine REAL stops (ATR-based) and REAL volume-spike detection
instead of the 4% fallback. Uses Alpaca if keys are set (best), else Yahoo's
free chart API (no key). Zero required dependencies.

    from bars import get_bars, atr, avg_volume, volume_spike
    b = get_bars("RKLB", timeframe="1d", limit=30)
    stop_dist = 1.5 * atr(b)          # ATR(14) volatility stop distance
    spike = volume_spike(b)           # today's volume / recent average
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from statistics import mean

log = logging.getLogger("aethercouncil.bars")
_UA = "Mozilla/5.0 (compatible; AetherCouncil/1.0)"


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _yahoo_bars(symbol: str, rng: str, interval: str) -> list[dict]:
    d = _http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                   f"?range={rng}&interval={interval}")
    res = (d.get("chart", {}).get("result") or [None])[0]
    if not res:
        return []
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    out = []
    for i in range(len(ts)):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        v = (q.get("volume") or [None] * len(ts))[i]
        if None in (o, h, l, c):
            continue
        t = datetime.fromtimestamp(ts[i], tz=timezone.utc).isoformat()
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return out


def _alpaca_bars(symbol: str, timeframe: str, limit: int) -> list[dict]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    key, sec = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    tf = {"1d": TimeFrame.Day, "1h": TimeFrame.Hour, "1m": TimeFrame.Minute}.get(
        timeframe, TimeFrame.Day)
    client = StockHistoricalDataClient(key, sec)
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, limit=limit)
    bars = client.get_stock_bars(req).data.get(symbol, [])
    return [{"o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in bars]


def get_bars(symbol: str, timeframe: str = "1d", limit: int = 30) -> list[dict]:
    """Alpaca if keys present, else Yahoo. Returns oldest->newest OHLCV dicts."""
    if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
        try:
            return _alpaca_bars(symbol, timeframe, limit)
        except Exception as e:  # noqa: BLE001
            log.warning("alpaca bars failed (%s), falling back to yahoo", e)
    rng = {"1d": "3mo", "1h": "1mo", "1m": "5d"}.get(timeframe, "3mo")
    return _yahoo_bars(symbol, rng, timeframe)[-limit:]


def atr(bars: list[dict], period: int = 14) -> float:
    """Wilder's Average True Range. 0.0 if not enough bars."""
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = mean(trs[:period])
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def avg_volume(bars: list[dict], n: int = 20) -> float:
    vs = [b["v"] for b in bars[-n:] if b["v"]]
    return mean(vs) if vs else 0.0


def volume_spike(bars: list[dict]) -> float:
    """Latest bar volume / trailing average. >1.5 is a notable spike."""
    if len(bars) < 2:
        return 0.0
    av = avg_volume(bars[:-1])
    return (bars[-1]["v"] / av) if av else 0.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    for sym in sys.argv[1:] or ["RKLB", "ASTS", "ACHR"]:
        b = get_bars(sym)
        if not b:
            print(f"{sym}: no bars"); continue
        a = atr(b)
        px = b[-1]["c"]
        print(f"{sym:6} px={px:.2f}  ATR(14)={a:.2f} ({a/px:.1%})  "
              f"1.5xATR stop=${px-1.5*a:.2f}  volspike={volume_spike(b):.2f}x  bars={len(b)}")
