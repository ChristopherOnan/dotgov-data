"""
universe.py — assemble + filter the tradable universe.

Sources (in priority): universe.txt (you paste Barchart Top 100 + your Robinhood
screener symbols here, one per line) else a large-cap default seed. Then it
EXCLUDES healthcare/pharma via Finnhub's industry classification, cached to disk.

    from universe import get_universe
    symbols = get_universe()      # health/pharma removed

Populate universe.txt with your real lists; classification needs FINNHUB_API_KEY.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("aethercouncil.universe")

# Watchlist source files, merged in order. Paste Barchart Top 100 into
# universe.txt and your Robinhood screener/list exports into robinhood_lists.txt.
UNIVERSE_FILES = [f.strip() for f in os.getenv(
    "UNIVERSE_FILES", "universe.txt,robinhood_lists.txt").split(",") if f.strip()]
UNIVERSE_FILE = os.getenv("UNIVERSE_FILE", "universe.txt")  # back-compat
SECTOR_CACHE = os.getenv("SECTOR_CACHE", "sector_cache.json")

# Substrings (lowercase) in Finnhub industry that mark health/pharma -> excluded.
EXCLUDE_KW = ("pharma", "biotech", "health", "medical", "drug", "therapeut",
              "life science", "hospital", "medicine", "clinic", "diagnostic",
              "dental", "genomic")

# Hard crypto guard — the user never trades crypto, so drop any coin/pair that
# sneaks in via a pasted list (tickers, -USD/ /USD pairs, or USD stablecoins).
CRYPTO_BLOCK = {
    "BTC", "ETH", "DOGE", "SOL", "XRP", "ADA", "AVAX", "LTC", "DOT", "SHIB",
    "MATIC", "LINK", "UNI", "BCH", "ETC", "XLM", "ALGO", "USDT", "USDC", "BNB",
    "TRX", "PEPE", "WIF", "BONK", "USD", "USDD",
}


def _is_crypto(sym: str) -> bool:
    s = sym.upper()
    if s in CRYPTO_BLOCK:
        return True
    # pair notations like BTC-USD, ETH/USD, DOGEUSD
    return bool(("-USD" in s) or ("/USD" in s) or (s.endswith("USD") and len(s) > 3))

# Fallback seed if universe.txt is absent (non-exhaustive large/active names).
DEFAULT_SEED = [
    "ASTS", "RKLB", "ACHR", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META",
    "GOOGL", "AMD", "AVGO", "PLTR", "SMCI", "MU", "MSTR", "COIN", "MARA", "SHOP",
    "NFLX", "CRM", "ORCL", "SNOW", "NET", "DDOG", "UBER", "ABNB", "SOFI", "HOOD",
    "BABA", "NIO", "F", "GM", "BA", "CAT", "XOM", "CVX", "JPM", "GS", "V", "MA",
    "DIS", "WMT", "COST", "HD", "NKE", "QCOM", "INTC", "TSM", "ARM", "DELL",
    "PANW", "CRWD", "ANET", "LRCX", "KLAC",
]


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "AetherCouncil/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _finnhub_industry(sym: str) -> str:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return ""
    try:
        d = _http_json(f"https://finnhub.io/api/v1/stock/profile2?symbol={sym}&token={key}")
        return d.get("finnhubIndustry", "") or ""
    except Exception as e:  # noqa: BLE001
        log.warning("industry lookup failed for %s: %s", sym, e)
        return ""


def _load_cache() -> dict:
    try:
        return json.load(open(SECTOR_CACHE)) if os.path.exists(SECTOR_CACHE) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(c: dict) -> None:
    try:
        json.dump(c, open(SECTOR_CACHE, "w"))
    except Exception:  # noqa: BLE001
        pass


def load_symbols() -> list[str]:
    """Merge every watchlist file that exists; fall back to the seed. Crypto is
    always dropped (user never trades crypto)."""
    syms: list[str] = []
    found = False
    for path in UNIVERSE_FILES:
        if os.path.exists(path):
            found = True
            for line in open(path):
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    syms.append(t.split()[0])   # tolerate "AAPL  Apple Inc"
    if not found:
        syms = list(DEFAULT_SEED)
    syms = [s for s in syms if not _is_crypto(s)]
    return list(dict.fromkeys(syms))  # dedupe, keep order


def is_health_or_pharma(industry: str) -> bool:
    return any(k in industry.lower() for k in EXCLUDE_KW)


def get_universe(filter_health: bool = True) -> list[str]:
    syms = load_symbols()
    if not filter_health:
        return syms
    cache = _load_cache()
    keep = []
    for s in syms:
        ind = cache.get(s)
        if ind is None:
            ind = _finnhub_industry(s)
            cache[s] = ind
        if not is_health_or_pharma(ind):
            keep.append(s)
        else:
            log.info("excluded %s (%s)", s, ind)
    _save_cache(cache)
    return keep


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    u = get_universe()
    print(f"universe ({len(u)} symbols after health/pharma filter):")
    print(", ".join(u))
