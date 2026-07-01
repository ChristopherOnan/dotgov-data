"""
autotrader.py — the last wire: stream signal -> gated council -> sized paper order.

This is the on_signal handler that makes everything one autonomous loop:

  stream_indicators signal (FREE, instant timing)
     -> risk gates (circuit breaker, token budget, cooldown, max positions)
     -> agent_pool.deliberate (cheap swarm; expert council only if it escalates)
     -> only act if consensus_prob >= ENTRY_PROB
     -> size by ATR risk (bars.atr) + trading_engine.position_size
     -> paper LIMIT order (execution gated by PAPER_EXECUTE / live gate)
     -> log every decision to calibration for scoring

Wire it to any feed:
    from finnhub_stream import stream
    from autotrader import AutoTrader
    from trading_engine import DailyRisk
    at = AutoTrader(DailyRisk(start_equity))
    await stream(get_universe(), on_signal=at.on_signal)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import calibration
from agent_pool import deliberate
from bars import atr, get_bars
from portfolio import Portfolio
from trading_engine import (
    DailyRisk, ENTRY_PROB, MAX_POSITIONS, MAX_SLIPPAGE, TRADING_MODE,
    account_snapshot, assert_live_allowed, position_size, stop_from_atr,
    submit_limit,
)

log = logging.getLogger("aethercouncil.autotrader")

COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "900"))        # sec between acts/symbol
PAPER_EXECUTE = os.getenv("PAPER_EXECUTE") == "1"
START_EQUITY = float(os.getenv("START_EQUITY", "10000"))


def _has_alpaca() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


class AutoTrader:
    def __init__(self, risk: DailyRisk | None = None, portfolio: Portfolio | None = None):
        self.risk = risk or DailyRisk(START_EQUITY)
        self.pf = portfolio or Portfolio()   # persistent paper positions
        self._last: dict[str, float] = {}

    @property
    def open_symbols(self) -> set[str]:
        return self.pf.open_symbols()

    async def on_signal(self, sym: str, sig) -> dict | None:
        # --- 1. risk / rate gates (all free) --------------------------------
        halted, why = self.risk.trading_halted()
        if halted:
            log.info("skip %s: %s", sym, why)
            return None
        if sig.action != "buy":              # exits handled by stops/sell rules
            return None
        now = time.time()
        if now - self._last.get(sym, 0) < COOLDOWN:
            return None
        if len(self.open_symbols) >= MAX_POSITIONS:
            log.info("skip %s: at max %d positions", sym, MAX_POSITIONS)
            return None

        # --- 2. gated deliberation (cheap swarm; council only if it escalates)
        d = await deliberate(
            f"Real-time BUY signal on {sym} at ${sig.price} "
            f"(RSI {sig.rsi:.0f}, {sig.why}). Enter long for a fast intraday/"
            f"overnight trade, or stand aside?",
            tickers=[sym],
        )
        self.risk.add_tokens(d.get("cost_usd") or 0.0)
        prob = d.get("consensus_prob")
        if not prob or prob < ENTRY_PROB:
            calibration.log_prediction(sym, prob or 0.5, "up", "intraday",
                                       note=f"declined @{sig.price}")
            log.info("stand aside %s: prob=%s < %.2f (cost $%.4f)",
                     sym, prob, ENTRY_PROB, d.get("cost_usd") or 0)
            return {"symbol": sym, "action": "stand_aside", "prob": prob}

        # --- 3. size by ATR risk -------------------------------------------
        bars = await asyncio.to_thread(get_bars, sym)
        stop = stop_from_atr(sig.price, atr(bars))
        if TRADING_MODE == "live":
            assert_live_allowed()
        if _has_alpaca():
            acct = await asyncio.to_thread(account_snapshot)
        else:
            acct = {"equity": START_EQUITY, "buying_power": START_EQUITY}
        qty = position_size(acct["equity"], sig.price, stop, acct["buying_power"])
        if qty <= 0:
            log.info("skip %s: sizing -> 0 shares (stop too wide / no BP)", sym)
            return {"symbol": sym, "action": "no_size"}

        # --- 4. execute (paper LIMIT) + log --------------------------------
        limit = round(sig.price * (1 + MAX_SLIPPAGE), 2)
        pid = calibration.log_prediction(sym, prob, "up", "intraday",
                                         note=f"entry qty={qty} stop={stop} lim={limit}")
        self._last[sym] = now
        # record the paper position (persistent) so the track record can score it
        self.pf.open(sym, qty=qty, entry=sig.price, stop=stop, prob=prob, pid=pid)
        order = None
        if PAPER_EXECUTE and _has_alpaca():
            order = await asyncio.to_thread(submit_limit, sym, qty, "buy", limit)
        log.info("ENTER %s qty=%d @limit %.2f stop %.2f prob %.2f pid=%s exec=%s cost=$%.4f",
                 sym, qty, limit, stop, prob, pid, bool(order), d.get("cost_usd") or 0)
        return {"symbol": sym, "action": "enter_long", "qty": qty, "limit": limit,
                "stop": stop, "prob": prob, "pid": pid, "order": order}


# end-to-end wiring test with a synthetic signal.
# needs OPENROUTER_API_KEY (real deliberation ~$0.002); no Alpaca keys required
# (falls back to START_EQUITY, and skips order placement unless PAPER_EXECUTE=1).
if __name__ == "__main__":
    import types
    logging.basicConfig(level=logging.INFO)

    async def _demo():
        at = AutoTrader(DailyRisk(10000))
        sig = types.SimpleNamespace(action="buy", price=100.0, rsi=28.0,
                                    why="RSI cross up from oversold")
        print(await at.on_signal("RKLB", sig))

    asyncio.run(_demo())
