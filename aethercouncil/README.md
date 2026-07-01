# AetherCouncil — autonomous trading stack

A cost-optimal, risk-first autonomous trading research + execution system.
Cheap agent swarm does breadth, a gated Claude/Grok/Gemini council makes the
high-level calls, real-time indicators handle timing, and everything is
budget-capped and calibration-gated before real money.

## Pipeline
```
finnhub_stream / bars ──▶ stream_indicators (live RSI/MACD/VWAP, FREE)
        │                          │ signal
        ▼                          ▼
   market_context ───▶ agent_pool.deliberate  (cheap swarm → GATED expert council)
        │                          │ decision
        ▼                          ▼
   trading_engine (risk sizing + ATR stops + LIMIT orders, paper-default)
        │
        ▼
   calibration (score every call) ◀── run_loop (always-on 24/5 + nightly report)
```

## Modules (all tested as noted)
| File | Role | Tested |
|---|---|---|
| `xai_resilient.py` | retry/backoff xAI client (fixes the 500s) | logic |
| `agent_pool.py` | cheap swarm + gated expert council, live cost ledger + budget cap | ✅ live ($0.006 full run) |
| `market_data.py` / `market_context.py` | live quotes → prompt injection | ✅ live |
| `bars.py` | OHLCV, ATR(14), volume-spike (Alpaca→Yahoo) | ✅ live + reference |
| `stream_indicators.py` | up-to-the-second RSI/MACD/VWAP | ✅ RSI exact vs reference |
| `finnhub_stream.py` | free real-time feed → signals | glue (needs key) |
| `trading_engine.py` | risk manager, watcher, LLM-gated, LIMIT orders | ✅ logic + live dry-run |
| `run_loop.py` | always-on 24/5 scheduler + nightly report | ✅ window logic + live cycle |
| `calibration.py` | Brier scoring / live-gate | ✅ |
| `validate_models.py` | fail loudly on bad model names | logic |
| `x_scout.py` | native X scanning via Grok x_search | glue (needs key) |
| `universe.py` | assemble watchlist, EXCLUDE health/pharma (Finnhub industry) | ✅ logic |
| `autotrader.py` | THE WIRE: signal→gated council→sized paper order | ✅ live end-to-end |
| `crypto_stream.py` | free 24/7 Binance WS → signals (round-the-clock) | glue (needs ws) |
| `backtest.py` | replay RSI/VWAP rules on history before paper | ✅ live |

## Quickstart (paper, safe)
```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=...          # rotate the one shared in chat!
export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...   # paper keys
python3 validate_models.py             # confirm model slugs
python3 run_loop.py --check            # 24/5 window open?
python3 run_loop.py --once             # one decision cycle (dry)
python3 run_loop.py                    # run forever (decision-only)
# to place PAPER orders: export PAPER_EXECUTE=1  (needs Alpaca paper keys)
```

## Cost
Data $0 (Finnhub/Alpaca free + Yahoo). Tokens ~$3–12/mo expected, hard-capped
at ~$60/mo by `DAILY_TOKEN_BUDGET`. Watcher/indicator loop is LLM-free ($0).

## Safety (do not skip)
- Paper-only until `calibration` Brier < 0.24 on a real sample AND positive
  paper PnL after costs.
- Live requires `TRADING_MODE=live` + `LIVE_CONFIRM=I_UNDERSTAND_THE_RISK` +
  the calibration gate.
- Margin only after live proves out, incrementally (start 1.2x, never 2x).
- Per-trade risk cap, exposure cap, daily loss circuit breaker, LIMIT-only.

See RESEARCH_AND_PLAN.md, TRADING_STRATEGY.md, DATA_FEEDS.md for the reasoning.
```
