"""
advisor.py — "Aether Council, what are the best stocks to buy right now?"

Answers on demand across the WHOLE universe (universe.txt + your Robinhood lists,
health/pharma excluded, crypto blocked). Two stages, cheap where it can be:

  1. FREE screen — pull live quotes for every name (in parallel), compute RSI on
     the movers, and classify each 🟢 GREEN / 🔴 RED / 🟡 WAIT. Costs $0.
  2. COUNCIL expertise — hand the pre-screened GREEN shortlist to the agent
     council (which may build sub-agents per name) for a decisive, plain-English
     pick. Costs a few tenths of a cent.

Output is written like you're 16: what to buy, why, and what to avoid. No jargon.

    python3 advisor.py                 # best buys across the whole universe now
    python3 advisor.py --n 5           # shortlist size for the council
    python3 advisor.py --fast          # skip the council (free screen only)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

log = logging.getLogger("aethercouncil.advisor")


@dataclass
class Row:
    sym: str
    price: float
    change_pct: float
    rsi: float
    color: str
    reason: str


def _classify(change_pct: float, rsi: float) -> tuple[str, str]:
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


def _rsi_for(sym: str) -> float:
    from bars import get_bars
    from stream_indicators import LiveTA
    try:
        bars = get_bars(sym, limit=60)
        if not bars or len(bars) <= 15:
            return 50.0
        ta = LiveTA()
        for b in bars:
            ta.update(b["c"], b.get("v", 0))
        return ta.rsi.value if ta.rsi.value is not None else 50.0
    except Exception:  # noqa: BLE001
        return 50.0


def screen(max_workers: int = 16, rsi_candidates: int = 30) -> list[Row]:
    """Free, parallel screen of the whole universe. Returns rows, GREEN-first."""
    from market_data import get_quote
    from universe import get_universe
    syms = get_universe()
    log.info("screening %d symbols...", len(syms))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        quotes = list(ex.map(get_quote, syms))

    live = [(q.symbol, q.price, q.change_pct or 0.0)
            for q in quotes if q.price is not None]
    # only spend RSI fetches on the biggest movers (up or down)
    movers = sorted(live, key=lambda x: abs(x[2]), reverse=True)[:rsi_candidates]
    mover_syms = {m[0] for m in movers}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rsis = dict(zip([m[0] for m in movers],
                        ex.map(_rsi_for, [m[0] for m in movers])))

    rows: list[Row] = []
    for sym, price, chg in live:
        rsi = rsis.get(sym, 50.0)
        color, reason = _classify(chg, rsi)
        rows.append(Row(sym, price, chg, rsi, color, reason))
    order = {"GREEN": 0, "WAIT": 1, "RED": 2}
    rows.sort(key=lambda r: (order[r.color], -r.change_pct))
    return rows


async def council_pick(greens: list[Row]) -> str:
    """Hand the GREEN shortlist to the council (with sub-agents) for a call."""
    if not greens:
        return "No green setups right now — the council says sit on your hands."
    from subagents import orchestrate
    lines = "\n".join(
        f"- {r.sym}: ${r.price:.2f} ({r.change_pct:+.1f}%), RSI {r.rsi:.0f}, {r.reason}"
        for r in greens
    )
    task = (
        "You are advising a beginner. From this pre-screened shortlist of bullish "
        "candidates with live data, pick the 3-5 BEST to buy for the next few days. "
        "For each pick: one plain-English sentence a 16-year-old understands on WHY, "
        "and name any you'd avoid. Be decisive.\n\n"
        f"SHORTLIST:\n{lines}"
    )
    out = await orchestrate(task, tickers=[r.sym for r in greens[:8]])
    return out["answer"] + f"\n\n(council cost ${out['cost_usd']:.4f}, "\
        f"sub-agents: {out['spawned']})"


def _board(rows: list[Row], n_green: int = 12, n_red: int = 8) -> str:
    dot = {"GREEN": "🟢", "RED": "🔴", "WAIT": "🟡"}
    greens = [r for r in rows if r.color == "GREEN"][:n_green]
    reds = [r for r in rows if r.color == "RED"][:n_red]
    out = ["🟢 BEST BUYS RIGHT NOW"]
    out += [f"  {dot[r.color]} {r.sym:6} ${r.price:8.2f} {r.change_pct:+6.1f}%  "
            f"RSI {r.rsi:4.0f}  {r.reason}" for r in greens] or ["  (none today)"]
    out += ["", "🔴 AVOID / EXIT"]
    out += [f"  {dot[r.color]} {r.sym:6} ${r.price:8.2f} {r.change_pct:+6.1f}%  "
            f"RSI {r.rsi:4.0f}  {r.reason}" for r in reds] or ["  (none today)"]
    return "\n".join(out)


async def best_stocks(shortlist_n: int = 6, fast: bool = False, notify_it: bool = False) -> dict:
    rows = await asyncio.to_thread(screen)
    greens = [r for r in rows if r.color == "GREEN"]
    board = _board(rows)
    verdict = ""
    if not fast:
        verdict = await council_pick(greens[:shortlist_n])
    text = board + ("\n\n=== COUNCIL VERDICT ===\n" + verdict if verdict else "")
    if notify_it:
        try:
            from notify import notify
            notify("Best stocks to buy", text)
        except Exception:  # noqa: BLE001
            pass
    return {"board": board, "verdict": verdict, "text": text,
            "green_count": len(greens), "scanned": len(rows)}


def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="council shortlist size")
    ap.add_argument("--fast", action="store_true", help="free screen only, no council")
    ap.add_argument("--notify", action="store_true", help="also push to your phone")
    args = ap.parse_args()
    out = asyncio.run(best_stocks(shortlist_n=args.n, fast=args.fast, notify_it=args.notify))
    print("\n" + out["text"])
    print(f"\n(scanned {out['scanned']} names, {out['green_count']} green)")


if __name__ == "__main__":
    _cli()
