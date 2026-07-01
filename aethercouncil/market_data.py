"""
market_data.py — stable live quote feed for AetherCouncil.

First-principles: the council gives shallow answers because the agents never
SEE live prices. Fix = fetch quotes from a stable source and inject them.
Robinhood is the wrong backbone (unofficial, 2FA, fragile — likely your
pulse OSError). This uses real sources with graceful fallback and ZERO new
dependencies (stdlib urllib only):

  1. Finnhub   — if FINNHUB_API_KEY is set (free tier works). Best.
  2. Yahoo     — no key, public chart JSON. Zero-config fallback.

Returns last-known data and a clear status instead of raising, so one bad
fetch never kills a council run.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("aethercouncil.market_data")

_TIMEOUT = 8.0
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")


@dataclass
class Quote:
    symbol: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    volume: Optional[float] = None
    source: str = "unavailable"

    def as_dict(self) -> dict:
        return asdict(self)


_UA = "Mozilla/5.0 (compatible; AetherCouncil/1.0)"


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode())


def _finnhub(symbol: str) -> Optional[Quote]:
    if not FINNHUB_KEY:
        return None
    try:
        d = _http_json(
            f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        )
        if not d or d.get("c") in (None, 0):
            return None
        prev = d.get("pc")
        cur = d.get("c")
        chg = ((cur - prev) / prev * 100.0) if prev else None
        return Quote(symbol, cur, chg, d.get("o"), d.get("h"), d.get("l"),
                     prev, None, "finnhub")
    except Exception as e:  # noqa: BLE001
        log.warning("finnhub %s failed: %s", symbol, e)
        return None


def _yahoo(symbol: str) -> Optional[Quote]:
    try:
        d = _http_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            "?interval=1d&range=1d"
        )
        res = (d.get("chart", {}).get("result") or [None])[0]
        if not res:
            return None
        meta = res.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        chg = ((price - prev) / prev * 100.0) if prev else None
        op = None
        try:
            opens = [o for o in res["indicators"]["quote"][0].get("open", [])
                     if o is not None]
            op = opens[0] if opens else None
        except (KeyError, IndexError, TypeError):
            op = None
        return Quote(symbol, price, chg, op,
                     meta.get("regularMarketDayHigh"),
                     meta.get("regularMarketDayLow"),
                     prev, meta.get("regularMarketVolume"), "yahoo")
    except Exception as e:  # noqa: BLE001
        log.warning("yahoo %s failed: %s", symbol, e)
        return None


def get_quote(symbol: str) -> Quote:
    symbol = symbol.upper().strip()
    return _finnhub(symbol) or _yahoo(symbol) or Quote(symbol)


def get_quotes(symbols: list[str]) -> dict[str, Quote]:
    return {s.upper(): get_quote(s) for s in symbols}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    syms = sys.argv[1:] or ["ASTS", "RKLB", "ACHR"]
    for s, q in get_quotes(syms).items():
        print(f"{s:6} {q.price}  ({q.change_pct:+.2f}%)  src={q.source}"
              if q.price else f"{s:6} unavailable")
