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
ENABLE_SHORTS = os.getenv("ENABLE_SHORTS", "1") == "1"     # short overextended names


def _has_alpaca() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


def _features_from(sig) -> dict:
    """Normalize a signal into memory features (setup type, RSI, move)."""
    why = (getattr(sig, "why", "") or "").lower()
    setup = ("oversold_bounce" if "oversold" in why else
             "overbought_fade" if "overbought" in why else "signal")
    return {"rsi": round(getattr(sig, "rsi", None) or 0, 0),
            "change_pct": getattr(sig, "change_pct", None),
            "setup": setup}


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
        # buy = long entry; sell = overextension -> possible SHORT entry
        if sig.action == "buy":
            side = "long"
        elif sig.action == "sell" and ENABLE_SHORTS:
            side = "short"
        else:
            return None
        now = time.time()
        if now - self._last.get(sym, 0) < COOLDOWN:
            return None
        if len(self.open_symbols) >= MAX_POSITIONS:
            log.info("skip %s: at max %d positions", sym, MAX_POSITIONS)
            return None
        if sym in self.open_symbols:         # never stack/flip on an open name
            return None
        # verify the price before any tokens or orders (bad data = no trade)
        try:
            from data_guard import verified_quote
            v = verified_quote(sym)
            if not v["trust"]:
                log.warning("skip %s: data_guard %s", sym, v["flags"])
                return None
        except Exception:  # noqa: BLE001
            pass

        # --- 2. gated deliberation (cheap swarm; council only if it escalates)
        # inject episodic memory of similar past setups (self-improvement)
        features = _features_from(sig)
        try:
            import memory
            recall = memory.recall(sym, features)
        except Exception:  # noqa: BLE001
            recall = ""
        if side == "long":
            q = (f"Real-time BUY signal on {sym} at ${sig.price} "
                 f"(RSI {sig.rsi:.0f}, {sig.why}). Enter long for a fast intraday/"
                 f"overnight trade, or stand aside? PROB = probability the trade "
                 f"is profitable.")
        else:
            q = (f"Real-time OVEREXTENSION signal on {sym} at ${sig.price} "
                 f"(RSI {sig.rsi:.0f}, {sig.why}): it just rolled over from "
                 f"overbought. Enter a SHORT to capture the fade, or stand aside? "
                 f"PROB = probability the SHORT is profitable.")
        d = await deliberate(q, tickers=[sym], extra_context=recall)
        self.risk.add_tokens(d.get("cost_usd") or 0.0)
        prob = d.get("consensus_prob")
        direction = "up" if side == "long" else "down"
        if not prob or prob < ENTRY_PROB:
            calibration.log_prediction(sym, prob or 0.5, direction, "intraday",
                                       note=f"declined {side} @{sig.price}")
            log.info("stand aside %s (%s): prob=%s < %.2f (cost $%.4f)",
                     sym, side, prob, ENTRY_PROB, d.get("cost_usd") or 0)
            return {"symbol": sym, "action": "stand_aside", "side": side, "prob": prob}

        # --- 3. size by ATR risk (stop mirrored for shorts) -----------------
        bars = await asyncio.to_thread(get_bars, sym)
        a = atr(bars)
        if side == "short":
            long_stop = stop_from_atr(sig.price, a)
            stop = round(2 * sig.price - long_stop, 2)   # same distance, ABOVE entry
        else:
            stop = stop_from_atr(sig.price, a)
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
        # long: buy up to limit above; short: sell down to limit below
        slip = MAX_SLIPPAGE if side == "long" else -MAX_SLIPPAGE
        limit = round(sig.price * (1 + slip), 2)
        pid = calibration.log_prediction(sym, prob, direction, "intraday",
                                         note=f"{side} qty={qty} stop={stop} lim={limit}")
        self._last[sym] = now
        # record the paper position (persistent) so the track record can score it
        self.pf.open(sym, qty=qty, entry=sig.price, stop=stop, prob=prob,
                     pid=pid, side=side)
        # feed the self-improvement loop: episodic memory + per-agent votes
        try:
            import memory
            memory.record(pid, sym, {**features, "side": side}, prob, note=sig.why)
        except Exception:  # noqa: BLE001
            pass
        try:
            import agent_scorecard
            agent_scorecard.record_votes(pid, d.get("votes") or {})
        except Exception:  # noqa: BLE001
            pass
        try:
            import journal
            journal.log_entry(sym, f"enter_{side}", prob, sig.why, d.get("cost_usd"))
        except Exception:  # noqa: BLE001
            pass
        order = None
        if PAPER_EXECUTE and _has_alpaca():
            broker_side = "buy" if side == "long" else "sell"
            order = await asyncio.to_thread(submit_limit, sym, qty, broker_side, limit)
        log.info("ENTER %s %s qty=%d @limit %.2f stop %.2f prob %.2f pid=%s exec=%s cost=$%.4f",
                 side.upper(), sym, qty, limit, stop, prob, pid, bool(order),
                 d.get("cost_usd") or 0)
        try:
            from notify import notify
            notify(f"{'📈 LONG' if side == 'long' else '📉 SHORT'} {sym}",
                   f"qty {qty} @ ~${sig.price:.2f}, stop ${stop:.2f}, "
                   f"prob {prob:.2f} — {sig.why}")
        except Exception:  # noqa: BLE001
            pass
        return {"symbol": sym, "action": f"enter_{side}", "side": side, "qty": qty,
                "limit": limit, "stop": stop, "prob": prob, "pid": pid, "order": order}


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
