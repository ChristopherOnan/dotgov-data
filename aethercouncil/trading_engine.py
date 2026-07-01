"""
trading_engine.py — risk-first autonomous trading for AetherCouncil.

Design (see TRADING_STRATEGY.md): watch for setups for FREE, spend tokens only
to DECIDE, size by RISK not by whim, and never trade live until a paper track
record clears the calibration gate. Broker = Alpaca (official 24/5 API, paper
trading, extended/overnight native).

Pipeline per cycle:
    watch (free, no LLM)  ->  on trigger: deliberate (cheap swarm, gated council)
    ->  risk check + sizing  ->  LIMIT order (paper by default)  ->  log to calibration

SAFETY DEFAULTS:
  • TRADING_MODE=paper unless you explicitly set it to "live"
  • live also requires LIVE_CONFIRM=I_UNDERSTAND_THE_RISK and a passing
    calibration gate (Brier < 0.24 on a real sample)
  • daily loss circuit breaker, per-trade risk cap, exposure cap, limit-only

Setup:  pip install alpaca-py openai
        export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...
        export OPENROUTER_API_KEY=...
Run  :  python3 trading_engine.py            # one paper scan cycle
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger("aethercouncil.engine")

# ---- config (env-overridable) ---------------------------------------------
TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower()   # paper | live
WATCHLIST = os.getenv("WATCHLIST", "ASTS,RKLB,ACHR").split(",")

RISK_FRAC = float(os.getenv("RISK_FRAC", "0.0075"))         # 0.75% equity/trade
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.20"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
DAILY_LOSS_HALT = float(os.getenv("DAILY_LOSS_HALT", "0.03"))  # -3% halts day
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.005"))    # 0.5% limit buffer
STOP_ATR_MULT = float(os.getenv("STOP_ATR_MULT", "1.5"))

# watcher triggers (free, no LLM)
GAP_THRESH = float(os.getenv("GAP_THRESH", "0.03"))         # 3% overnight gap
MOVE_THRESH = float(os.getenv("MOVE_THRESH", "0.05"))       # 5% intraday move

# escalate to a trade only above this council/swarm probability
ENTRY_PROB = float(os.getenv("ENTRY_PROB", "0.65"))
DAILY_TOKEN_BUDGET = float(os.getenv("DAILY_TOKEN_BUDGET", "2.00"))  # USD/day


# ---- pure, testable logic --------------------------------------------------
@dataclass
class Setup:
    symbol: str
    price: float
    change_pct: float
    reason: str
    strength: float   # 0..1 rough priority


def scan_setups(quotes: dict) -> list[Setup]:
    """FREE setup detection from live quotes. No LLM. Returns triggered setups."""
    setups: list[Setup] = []
    for sym, q in quotes.items():
        price = getattr(q, "price", None)
        if price is None:
            continue
        chg = (getattr(q, "change_pct", None) or 0.0) / 100.0
        prev = getattr(q, "prev_close", None)
        gap = ((getattr(q, "open", None) or price) - prev) / prev if prev else 0.0
        reasons, strength = [], 0.0
        if abs(gap) >= GAP_THRESH:
            reasons.append(f"gap {gap:+.1%}")
            strength = max(strength, min(1.0, abs(gap) / 0.10))
        if abs(chg) >= MOVE_THRESH:
            reasons.append(f"move {chg:+.1%}")
            strength = max(strength, min(1.0, abs(chg) / 0.10))
        if reasons:
            setups.append(Setup(sym, price, chg * 100, ", ".join(reasons), strength))
    return sorted(setups, key=lambda s: s.strength, reverse=True)


def position_size(equity: float, entry: float, stop: float,
                  buying_power: float) -> int:
    """Shares sized so a stop-out loses ~RISK_FRAC of equity. Capped by
    exposure and buying power. Returns whole shares (0 if not viable)."""
    per_share_risk = entry - stop
    if per_share_risk <= 0 or entry <= 0:
        return 0
    by_risk = (equity * RISK_FRAC) / per_share_risk
    by_exposure = (equity * MAX_POSITION_PCT) / entry
    by_bp = buying_power / entry
    return max(0, int(math.floor(min(by_risk, by_exposure, by_bp))))


def stop_from_atr(entry: float, atr: float) -> float:
    """Volatility-based stop. Falls back to a 4% stop if no ATR."""
    dist = STOP_ATR_MULT * atr if atr > 0 else entry * 0.04
    return round(entry - dist, 2)


STATE_PATH = os.getenv("RISK_STATE_PATH", "daily_risk.json")


class DailyRisk:
    """Tracks intraday PnL and enforces the circuit breaker + token budget.

    State persists to disk so a restart does NOT reset the daily loss breaker or
    token budget mid-day (that would defeat the safety limits). On load, if the
    saved day is stale it rolls over to a clean slate automatically.
    """
    def __init__(self, start_equity: float, persist_path: str | None = STATE_PATH):
        self.start_equity = start_equity
        self.realized = 0.0
        self.tokens_spent = 0.0
        self.day = datetime.now(timezone.utc).date()
        self.persist_path = persist_path
        self.load()

    def _rollover(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.realized = 0.0
            self.tokens_spent = 0.0
            self.day = today
            self.save()

    def to_dict(self) -> dict:
        return {"start_equity": self.start_equity, "realized": self.realized,
                "tokens_spent": self.tokens_spent, "day": self.day.isoformat()}

    def save(self) -> None:
        if not self.persist_path:
            return
        try:
            import json
            with open(self.persist_path, "w") as f:
                json.dump(self.to_dict(), f)
        except Exception as e:  # noqa: BLE001
            log.warning("risk state save failed: %s", e)

    def load(self) -> None:
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            import json
            from datetime import date
            with open(self.persist_path) as f:
                d = json.load(f)
            saved_day = date.fromisoformat(d.get("day", ""))
            if saved_day == datetime.now(timezone.utc).date():
                # same UTC day: resume running totals (breaker/budget intact)
                self.realized = float(d.get("realized", 0.0))
                self.tokens_spent = float(d.get("tokens_spent", 0.0))
                self.day = saved_day
                log.info("resumed risk state: realized=%.2f tokens=$%.4f",
                         self.realized, self.tokens_spent)
            # stale day → keep the fresh zeros from __init__
        except Exception as e:  # noqa: BLE001
            log.warning("risk state load failed: %s", e)

    def add_tokens(self, cost: float) -> None:
        self.tokens_spent += cost or 0.0
        self.save()

    def add_realized(self, pnl: float) -> None:
        self.realized += pnl or 0.0
        self.save()

    def trading_halted(self) -> tuple[bool, str]:
        self._rollover()
        if self.start_equity and self.realized <= -DAILY_LOSS_HALT * self.start_equity:
            return True, f"daily loss circuit breaker ({self.realized:.2f})"
        if self.tokens_spent >= DAILY_TOKEN_BUDGET:
            return True, f"daily token budget spent (${self.tokens_spent:.2f})"
        return False, ""


# ---- live-trading gate -----------------------------------------------------
def assert_live_allowed() -> None:
    """Refuse to trade live unless explicitly confirmed AND calibration passes."""
    if TRADING_MODE != "live":
        return
    if os.getenv("LIVE_CONFIRM") != "I_UNDERSTAND_THE_RISK":
        raise RuntimeError("LIVE mode requires LIVE_CONFIRM=I_UNDERSTAND_THE_RISK")
    try:
        from calibration import brier_score
        bs = brier_score()
    except Exception:  # noqa: BLE001
        bs = None
    if bs is None or bs >= 0.24:
        raise RuntimeError(
            f"LIVE blocked: calibration gate not passed (Brier={bs}). "
            "Paper-trade until Brier < 0.24 on a real sample."
        )


# ---- Alpaca order routing (lazy import so the module loads without the SDK) -
def _alpaca_client():
    from alpaca.trading.client import TradingClient
    key, sec = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and sec):
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    return TradingClient(key, sec, paper=(TRADING_MODE != "live"))


def submit_limit(symbol: str, qty: int, side: str, limit_price: float,
                 extended: bool = True) -> dict:
    """LIMIT order only (safe for thin extended/overnight books)."""
    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    client = _alpaca_client()
    req = LimitOrderRequest(
        symbol=symbol, qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY, limit_price=round(limit_price, 2),
        extended_hours=extended,
    )
    o = client.submit_order(req)
    log.info("%s order: %s %d %s @ %.2f", TRADING_MODE, side, qty, symbol, limit_price)
    return {"id": str(o.id), "symbol": symbol, "qty": qty, "side": side}


def account_snapshot() -> dict:
    c = _alpaca_client()
    a = c.get_account()
    return {"equity": float(a.equity), "buying_power": float(a.buying_power),
            "positions": len(c.get_all_positions())}


# ---- one decision cycle ----------------------------------------------------
async def run_cycle(dry_run: bool = True) -> dict:
    """Watch -> (on trigger) decide -> risk-check -> (paper) order. Token-frugal."""
    from market_data import get_quotes
    quotes = await asyncio.to_thread(get_quotes, WATCHLIST)
    setups = scan_setups(quotes)
    out = {"scanned": len(quotes), "setups": [s.__dict__ for s in setups],
           "decisions": [], "mode": TRADING_MODE, "dry_run": dry_run}
    if not setups:
        log.info("no setups — $0 spent, no tokens used")
        return out

    from agent_pool import deliberate
    for s in setups[:MAX_POSITIONS]:
        d = await deliberate(
            f"Setup on {s.symbol}: {s.reason} at ${s.price}. Enter long, "
            f"exit, or stand aside for an overnight/catalyst hold?",
            tickers=[s.symbol],
        )
        prob = d.get("consensus_prob")
        act = "enter_long" if (prob and prob >= ENTRY_PROB) else "stand_aside"
        out["decisions"].append({"symbol": s.symbol, "prob": prob,
                                 "action": act, "cost_usd": d.get("cost_usd")})
        # NOTE: real order placement (below) intentionally left behind dry_run
        # until you've paper-validated. Sizing/stop wiring shown for review.
        if act == "enter_long" and not dry_run:
            assert_live_allowed()
            acct = await asyncio.to_thread(account_snapshot)
            from bars import get_bars, atr as _atr
            b = await asyncio.to_thread(get_bars, s.symbol)
            stop = stop_from_atr(s.price, _atr(b))   # REAL volatility stop
            qty = position_size(acct["equity"], s.price, stop, acct["buying_power"])
            if qty > 0:
                limit = round(s.price * (1 + MAX_SLIPPAGE), 2)
                await asyncio.to_thread(submit_limit, s.symbol, qty, "buy", limit)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    print(json.dumps(asyncio.run(run_cycle(dry_run=True)), indent=2, default=str))
