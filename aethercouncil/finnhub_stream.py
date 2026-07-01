"""
finnhub_stream.py — free real-time trade stream -> live indicators.

Wires Finnhub's free WebSocket (real-time US trades, <100ms) into LiveTA so you
get up-to-the-second RSI/MACD/VWAP and rule-based buy/sell signals at zero cost.
The fast loop is LLM-FREE; only actionable signals get escalated to agent_pool.

Deps: pip install websockets      Set: FINNHUB_API_KEY (free tier)
Run : python3 finnhub_stream.py ASTS RKLB

NOTE: needs a key + network, so it isn't unit-tested here — but it's thin glue
over stream_indicators.py (which IS tested). Alpaca's stream is a drop-in swap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from stream_indicators import LiveTA

log = logging.getLogger("aethercouncil.stream")
WS_URL = "wss://ws.finnhub.io?token={key}"


async def stream(symbols: list[str], on_signal=None) -> None:
    import websockets  # lazy
    key = os.environ["FINNHUB_API_KEY"]
    ta = {s: LiveTA() for s in symbols}
    async for ws in websockets.connect(WS_URL.format(key=key)):   # auto-reconnect
        try:
            for s in symbols:
                await ws.send(json.dumps({"type": "subscribe", "symbol": s}))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") != "trade":
                    continue
                for t in msg.get("data", []):
                    sym, price, size = t["s"], float(t["p"]), float(t.get("v", 0))
                    sig = ta[sym].update(price, size)
                    if sig.action:
                        log.info("%s %s @ %.4f (RSI=%.1f) — %s",
                                 sym, sig.action.upper(), price,
                                 sig.rsi or 0, sig.why)
                        if on_signal:
                            await on_signal(sym, sig)
        except Exception as e:  # noqa: BLE001 - reconnect on any drop
            log.warning("stream dropped, reconnecting: %s", e)
            continue


async def _demo_handler(sym, sig):
    # Here you'd gate to agent_pool.deliberate() only on a signal, then size
    # via trading_engine.position_size and place a LIMIT order. Kept inert here.
    print(f"[SIGNAL] {sym} {sig.action} px={sig.price} rsi={sig.rsi:.1f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(stream(sys.argv[1:] or ["AAPL"], on_signal=_demo_handler))
