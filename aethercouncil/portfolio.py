"""
portfolio.py — the paper track record that decides if we have real edge.

This is the proof-of-edge engine. Every entry the autotrader makes is recorded
here as a paper position with an entry, a stop, and a take-profit target. A
resolver later replays real market bars since entry to see what actually would
have happened (stop hit? target hit? timed out?), closes the position, books the
PnL, and resolves the matching calibration prediction with the true outcome.

From that we compute the only numbers that matter before risking real money:
  • realized paper PnL after modeled costs
  • win rate / average return
  • Brier score (are the council's probabilities actually calibrated?)
  • GATE: cleared for live only if Brier < LIVE_BRIER_MAX and paper PnL > 0

State persists to PORTFOLIO_PATH (JSON) so a restart never loses positions —
this doubles as the persistent open-position store the autotrader reconciles to.

    from portfolio import Portfolio
    pf = Portfolio()
    pf.open("RKLB", qty=4, entry=101.65, stop=86.18, prob=0.68, pid="abc123")
    pf.resolve_open()          # replay bars, close what's done, score it
    print(pf.track_record_str())
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import calibration

log = logging.getLogger("aethercouncil.portfolio")

PORTFOLIO_PATH = os.getenv("PORTFOLIO_PATH", "paper_portfolio.json")
TARGET_R = float(os.getenv("TARGET_R", "2.0"))        # take-profit at 2x risk
MAX_HOLD_DAYS = int(os.getenv("MAX_HOLD_DAYS", "5"))  # time-stop
COST_PER_TRADE = float(os.getenv("COST_PER_TRADE", "0.0005"))  # 5bps round-trip
LIVE_BRIER_MAX = float(os.getenv("LIVE_BRIER_MAX", "0.24"))
MIN_TRADES_FOR_GATE = int(os.getenv("MIN_TRADES_FOR_GATE", "20"))


@dataclass
class Position:
    symbol: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_ts: str
    prob: float = 0.5
    pid: str = ""              # calibration prediction id
    status: str = "open"      # open | closed
    exit_price: Optional[float] = None
    exit_ts: Optional[str] = None
    exit_reason: str = ""     # stop | target | time
    ret: Optional[float] = None   # fractional return after cost


def _target_from(entry: float, stop: float, r: float | None = None) -> float:
    if r is None:
        try:
            from params import P
            r = float(P("target_r", TARGET_R))
        except Exception:  # noqa: BLE001
            r = TARGET_R
    risk = entry - stop
    return round(entry + r * risk, 2) if risk > 0 else round(entry * 1.04, 2)


def _max_hold() -> int:
    try:
        from params import P
        return int(P("max_hold", MAX_HOLD_DAYS))
    except Exception:  # noqa: BLE001
        return MAX_HOLD_DAYS


class Portfolio:
    def __init__(self, path: str = PORTFOLIO_PATH):
        self.path = path
        self.positions: list[Position] = []
        self.load()

    # ---- persistence -------------------------------------------------------
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                raw = json.load(f)
            self.positions = [Position(**p) for p in raw.get("positions", [])]
        except Exception as e:  # noqa: BLE001
            log.warning("portfolio load failed (%s); starting empty", e)
            self.positions = []

    def save(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump({"positions": [asdict(p) for p in self.positions]}, f, indent=2)
        except Exception as e:  # noqa: BLE001
            log.warning("portfolio save failed: %s", e)

    # ---- open / query ------------------------------------------------------
    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.positions if p.status == "open"}

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]

    def open(self, symbol: str, qty: int, entry: float, stop: float,
             prob: float = 0.5, pid: str = "", target: Optional[float] = None) -> Position:
        pos = Position(
            symbol=symbol.upper(), qty=qty, entry=round(entry, 2),
            stop=round(stop, 2), target=target or _target_from(entry, stop),
            entry_ts=datetime.now(timezone.utc).isoformat(), prob=prob, pid=pid,
        )
        self.positions.append(pos)
        self.save()
        log.info("OPEN %s qty=%d entry=%.2f stop=%.2f target=%.2f",
                 pos.symbol, qty, pos.entry, pos.stop, pos.target)
        return pos

    # ---- resolution --------------------------------------------------------
    def _resolve_one(self, pos: Position) -> bool:
        """Replay daily bars since entry; close on stop/target/time. True if closed."""
        from bars import get_bars
        max_hold = _max_hold()
        try:
            bars = get_bars(pos.symbol, timeframe="1d", limit=max_hold + 5)
        except Exception as e:  # noqa: BLE001
            log.warning("resolve %s: no bars (%s)", pos.symbol, e)
            return False
        if not bars:
            return False
        entry_day = pos.entry_ts[:10]
        # bars strictly after the entry day are the ones that can resolve it
        after = [b for b in bars if str(b.get("t", ""))[:10] > entry_day]
        held = 0
        for b in after:
            held += 1
            hi, lo, close = b.get("h"), b.get("l"), b.get("c")
            if lo is not None and lo <= pos.stop:
                return self._close(pos, pos.stop, "stop", held)
            if hi is not None and hi >= pos.target:
                return self._close(pos, pos.target, "target", held)
            if held >= max_hold:
                return self._close(pos, close, "time", held)
        return False  # still open, not enough bars yet

    def _close(self, pos: Position, exit_price: float, reason: str, held: int) -> bool:
        pos.status = "closed"
        pos.exit_price = round(exit_price, 2)
        pos.exit_ts = datetime.now(timezone.utc).isoformat()
        pos.exit_reason = reason
        pos.ret = round((exit_price - pos.entry) / pos.entry - COST_PER_TRADE, 5)
        outcome = 1 if pos.ret > 0 else 0
        if pos.pid:
            calibration.resolve_prediction(pos.pid, outcome)
            # feed the self-improvement loop with the true outcome
            try:
                import memory
                memory.resolve(pos.pid, outcome, pos.ret)
            except Exception:  # noqa: BLE001
                pass
            try:
                import agent_scorecard
                agent_scorecard.resolve_votes(pos.pid, outcome)
            except Exception:  # noqa: BLE001
                pass
        log.info("CLOSE %s @%.2f (%s, held %dd) ret=%.2f%% -> outcome=%d",
                 pos.symbol, exit_price, reason, held, pos.ret * 100, outcome)
        return True

    def resolve_open(self) -> dict:
        """Try to close every open position from real bars. Returns a summary."""
        closed, realized_frac = 0, 0.0
        for pos in self.open_positions():
            if self._resolve_one(pos):
                closed += 1
                realized_frac += pos.ret or 0.0
        if closed:
            self.save()
        return {"closed": closed, "realized_return": round(realized_frac, 5),
                "still_open": len(self.open_positions())}

    def realized_pnl_dollars(self) -> float:
        """Sum of $ PnL over all closed positions (qty * entry * ret)."""
        return round(sum((p.ret or 0.0) * p.entry * p.qty
                         for p in self.positions if p.status == "closed"), 2)

    # ---- track record + live gate -----------------------------------------
    def track_record(self) -> dict:
        closed = [p for p in self.positions if p.status == "closed"]
        rets = [p.ret for p in closed if p.ret is not None]
        wins = [r for r in rets if r > 0]
        total = 1.0
        for r in rets:
            total *= (1 + r)
        brier = calibration.brier_score()
        gate_ok = (
            brier is not None and brier < LIVE_BRIER_MAX
            and self.realized_pnl_dollars() > 0
            and len(closed) >= MIN_TRADES_FOR_GATE
        )
        return {
            "closed_trades": len(closed),
            "open_trades": len(self.open_positions()),
            "win_rate": round(len(wins) / len(rets), 3) if rets else None,
            "avg_return_pct": round(sum(rets) / len(rets) * 100, 3) if rets else None,
            "total_return_pct": round((total - 1) * 100, 2) if rets else 0.0,
            "realized_pnl_usd": self.realized_pnl_dollars(),
            "brier": round(brier, 4) if brier is not None else None,
            "min_trades_needed": MIN_TRADES_FOR_GATE,
            "live_gate_cleared": gate_ok,
        }

    def track_record_str(self) -> str:
        t = self.track_record()
        gate = ("✅ CLEARED FOR LIVE" if t["live_gate_cleared"]
                else "🔒 NOT cleared — keep paper trading")
        brier = f"{t['brier']}" if t["brier"] is not None else "n/a"
        wr = f"{t['win_rate']*100:.0f}%" if t["win_rate"] is not None else "n/a"
        return (
            "=== PAPER TRACK RECORD ===\n"
            f"closed trades   : {t['closed_trades']} (need {t['min_trades_needed']} for gate)\n"
            f"open trades     : {t['open_trades']}\n"
            f"win rate        : {wr}\n"
            f"avg return/trade: {t['avg_return_pct']}%\n"
            f"total return    : {t['total_return_pct']}%\n"
            f"realized PnL    : ${t['realized_pnl_usd']}\n"
            f"Brier score     : {brier}  (need < {LIVE_BRIER_MAX})\n"
            f"LIVE GATE       : {gate}"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import sys
    pf = Portfolio()
    if "--resolve" in sys.argv:
        print("resolve:", pf.resolve_open())
    print(pf.track_record_str())
