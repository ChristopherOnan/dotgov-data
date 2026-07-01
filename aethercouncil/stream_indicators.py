"""
stream_indicators.py — up-to-the-second technical analysis, computed locally.

First principles: indicators are deterministic functions of price, so we don't
pay an API for them — we compute them incrementally from a free real-time price
stream, O(1) per tick, zero dependencies. This is faster (no round trip),
cheaper (free), and unlimited (any indicator).

The fast loop here is LLM-FREE: it turns a price stream into real-time signals
in microseconds. The LLM (agent_pool) only decides WHICH signals to act on.

Wire a free feed (Finnhub / Alpaca / a crypto exchange WS) to LiveTA.update():

    ta = LiveTA()
    async for trade in feed:                 # your websocket loop
        sig = ta.update(trade.price, trade.size)
        if sig.action:                       # e.g. "buy" on RSI cross up from oversold
            ...hand to trading_engine / agent_pool...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class RSI:
    """Wilder's RSI, updated one price at a time."""
    def __init__(self, period: int = 14):
        self.period = period
        self.prev: Optional[float] = None
        self.avg_gain: Optional[float] = None
        self.avg_loss: Optional[float] = None
        self._g: list[float] = []
        self._l: list[float] = []
        self.value: Optional[float] = None

    def update(self, price: float) -> Optional[float]:
        if self.prev is None:
            self.prev = price
            return None
        change = price - self.prev
        self.prev = price
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if self.avg_gain is None:
            self._g.append(gain)
            self._l.append(loss)
            if len(self._g) < self.period:
                return None
            self.avg_gain = sum(self._g) / self.period
            self.avg_loss = sum(self._l) / self.period
        else:
            p = self.period
            self.avg_gain = (self.avg_gain * (p - 1) + gain) / p
            self.avg_loss = (self.avg_loss * (p - 1) + loss) / p
        if self.avg_loss == 0:
            self.value = 100.0
        else:
            rs = self.avg_gain / self.avg_loss
            self.value = 100.0 - 100.0 / (1.0 + rs)
        return self.value


class EMA:
    def __init__(self, period: int):
        self.k = 2.0 / (period + 1)
        self.value: Optional[float] = None

    def update(self, price: float) -> float:
        self.value = price if self.value is None else price * self.k + self.value * (1 - self.k)
        return self.value


class MACD:
    def __init__(self, fast=12, slow=26, signal=9):
        self.f, self.s, self.sig = EMA(fast), EMA(slow), EMA(signal)
        self.macd: Optional[float] = None
        self.signal: Optional[float] = None
        self.hist: Optional[float] = None

    def update(self, price: float):
        f, s = self.f.update(price), self.s.update(price)
        self.macd = f - s
        self.signal = self.sig.update(self.macd)
        self.hist = self.macd - self.signal
        return self.macd, self.signal, self.hist


class VWAP:
    """Session VWAP. Call reset() at each new session."""
    def __init__(self):
        self.pv = 0.0
        self.vol = 0.0
        self.value: Optional[float] = None

    def reset(self):
        self.pv = self.vol = 0.0
        self.value = None

    def update(self, price: float, size: float) -> Optional[float]:
        self.pv += price * size
        self.vol += size
        if self.vol > 0:
            self.value = self.pv / self.vol
        return self.value


@dataclass
class Signal:
    price: float
    rsi: Optional[float] = None
    macd_hist: Optional[float] = None
    vwap: Optional[float] = None
    action: Optional[str] = None   # "buy" | "sell" | None
    why: str = ""


class LiveTA:
    """Aggregates indicators + emits a real-time signal per tick. LLM-free."""
    def __init__(self, rsi_period=14, oversold=30.0, overbought=70.0,
                 require_vwap=False):
        self.rsi = RSI(rsi_period)
        self.macd = MACD()
        self.vwap = VWAP()
        self.oversold = oversold
        self.overbought = overbought
        self.require_vwap = require_vwap   # if True, only buy at/above VWAP
        self._prev_rsi: Optional[float] = None

    def update(self, price: float, size: float = 0.0) -> Signal:
        r = self.rsi.update(price)
        _, _, hist = self.macd.update(price)
        vw = self.vwap.update(price, size) if size else self.vwap.value
        action, why = None, ""
        # Real-time entry/exit rules (all free, instant):
        if r is not None and self._prev_rsi is not None:
            # RSI crossing UP out of oversold = mean-reversion long. VWAP is
            # informational by default (an oversold bounce is usually BELOW
            # VWAP); set require_vwap=True to demand a VWAP reclaim instead.
            vwap_ok = (not self.require_vwap) or vw is None or price >= vw
            if self._prev_rsi <= self.oversold < r and vwap_ok:
                action, why = "buy", f"RSI cross up {r:.0f} from oversold"
            # RSI crossing DOWN out of overbought = exit/short signal
            elif self._prev_rsi >= self.overbought > r:
                action, why = "sell", f"RSI cross down {r:.0f} from overbought"
        self._prev_rsi = r if r is not None else self._prev_rsi
        return Signal(price, r, hist, vw, action, why)


if __name__ == "__main__":
    # sanity demo
    prices = [44,44.3,44.1,43.6,44.3,44.8,45.1,45.4,45.1,45.6,46.2,46.1,46.4,46,46.0,
              45.6,46.2,46.2,46.0,46.0,46.4,46.2,45.6,46.2,46.2,46.0]
    ta = LiveTA()
    for p in prices:
        s = ta.update(p, size=100)
        if s.rsi is not None:
            tag = f"  <-- {s.action} ({s.why})" if s.action else ""
            print(f"px={p:6.2f}  RSI={s.rsi:5.1f}  VWAP={s.vwap:6.2f}  MACDh={s.macd_hist:+.3f}{tag}")
