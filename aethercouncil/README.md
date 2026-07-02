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
| `agent_pool.py` | cheap swarm + gated expert council, live cost ledger + budget cap | ✅ live ($0.006 full run) |
| `market_data.py` / `market_context.py` | live quotes → prompt injection | ✅ live |
| `bars.py` | OHLCV, ATR(14), volume-spike (Alpaca→Yahoo) | ✅ live + reference |
| `stream_indicators.py` | up-to-the-second RSI/MACD/VWAP | ✅ RSI exact vs reference |
| `finnhub_stream.py` | free real-time feed → signals | glue (needs key) |
| `trading_engine.py` | risk manager, watcher, LLM-gated, LIMIT orders | ✅ logic + live dry-run |
| `run_loop.py` | always-on 24/5 scheduler + nightly green/red board + daily scout | ✅ live cycle + board |
| `calibration.py` | Brier scoring / live-gate | ✅ |
| `validate_models.py` | fail loudly on bad model slugs (vs live OpenRouter list) | ✅ live |
| `daily_scout.py` | **daily research agents: scan X/web for new models/strategies/tools/catalysts** | ✅ live ($0.03/run) |
| `subagents.py` | **agents build+manage their own sub-agents on demand (depth/fanout/budget capped)** | ✅ live (spawn + caps) |
| `portfolio.py` | **paper track record: resolve trades on real bars, score calibration, live-gate** | ✅ live (resolve+gate) |
| `notify.py` | push alerts to phone (Telegram/email, console fallback) | ✅ live (console) |
| `data_guard.py` | **verify prices: cross-source + outlier reject (clean data for learning)** | ✅ live (catches spikes) |
| `memory.py` | **episodic memory: recall similar past setups + outcomes** | ✅ live (recall+resolve) |
| `agent_scorecard.py` | **skill-weight agents by tracked Brier (trust who earns it)** | ✅ live (weights) |
| `reflection.py` | **nightly: distill outcomes into reusable trading rules** | ✅ live (rules) |
| `tuner.py` / `params.py` | **weekly OOS-gated self-tuning of RSI/stop params (no overfit)** | ✅ live (gate held) |
| `journal.py` | **shared blackboard: recent decisions + open positions in every prompt** | ✅ live |
| `x_scout.py` | native X scanning via Grok x_search (used by scout when XAI_API_KEY set) | glue (needs xAI key) |
| `xai_resilient.py` | retry/backoff direct-xAI client (env-based) | logic |
| `universe.py` | merge Barchart-100 + Robinhood lists, EXCLUDE health/pharma, block crypto | ✅ live (119 names) |
| `advisor.py` | **"best stocks to buy?" — screen whole universe → council picks, plain English** | ✅ live ($0.0002) |
| `autotrader.py` | THE WIRE: signal→verified→gated council→sized LONG or SHORT paper order | ✅ live (both sides) |
| `backtest.py` | replay RSI/VWAP rules on history before paper | ✅ live |

_No crypto module: this stack never monitors or trades crypto by design._

## Daily research scout
`daily_scout.py` runs several scanner agents in parallel (one per theme:
agent-frameworks, models, market-data, strategies, catalysts), dedupes against
what it's already surfaced, then a curator agent ranks survivors ADOPT/TEST/
WATCH/SKIP and writes a dated brief to `scout_digests/YYYY-MM-DD.md`.
- With `XAI_API_KEY` set → scans **all of X/Twitter** natively via Grok x_search.
- Without it → OpenRouter web search (works today; ~$0.03/run).
- Fires automatically once/day at `SCOUT_HOUR` inside `run_loop.py`, or run it
  standalone: `python3 daily_scout.py` (or `python3 run_loop.py --scout` for cron).

## Self-improving loop
The system gets better the longer it runs (no fine-tuning): verified data →
memory of similar past trades → skill-weighted agent votes → paper outcomes →
nightly reflection that distills **reusable rules** injected back into decisions.
See **SELF_IMPROVEMENT.md** for the full architecture and research basis.
```bash
python3 run_loop.py --reflect   # run the learning step, print learned rules
python3 run_loop.py --track     # proof-of-edge: track record + live gate
```

## Ask the council: best stocks to buy
`advisor.py` answers on demand across the **whole universe** (universe.txt +
robinhood_lists.txt, health/pharma excluded, crypto blocked). It runs a free
parallel screen (live price + RSI → 🟢/🔴/🟡) of all ~120 names, then hands the
green shortlist to the council (which may build sub-agents per name) for a
decisive, plain-English pick.
```bash
python3 advisor.py            # best buys now + council verdict (~$0.0002)
python3 advisor.py --fast     # free screen only, no council
python3 run_loop.py --picks   # same, via the loop entrypoint
```
Grow coverage anytime: add tickers to `universe.txt`, or paste your Robinhood
screener/watchlist exports into `robinhood_lists.txt` — both are merged & de-duped.

## Universe
Trading coverage is the **universe**, not the scout's 5 research themes (those
scan the outside world for new tools). universe.py loads Barchart-100-style
liquid names + your Robinhood lists, drops health/pharma (Finnhub industry), and
hard-blocks crypto. `python3 universe.py` prints the current list.

## Quickstart (paper, safe)
```bash
pip install -r requirements.txt
cp .env.example .env                    # then fill in your keys (never commit .env)
python3 validate_models.py             # confirm model slugs vs live list
python3 run_loop.py --check            # 24/5 window open?
python3 run_loop.py --once             # one decision cycle (dry)
python3 daily_scout.py                 # one research scan → today's digest
python3 run_loop.py                    # run forever (trading loop + daily scout)
# to place PAPER orders: export PAPER_EXECUTE=1  (needs Alpaca paper keys)
```

### Daily scout via cron (e.g. on GCP), if not using run_loop's built-in timer
```cron
# 07:00 America/New_York every weekday — daily research digest
0 7 * * 1-5  cd /path/to/aethercouncil && /usr/bin/python3 run_loop.py --scout >> scout.log 2>&1
```

## Cost
Data $0 (Finnhub/Alpaca free + Yahoo). Trading tokens ~$3–12/mo expected,
hard-capped by `DAILY_TOKEN_BUDGET`. Daily scout ~$0.03/run → ~$1/mo (web mode).
Watcher/indicator loop is LLM-free ($0).

## Safety (do not skip)
- Paper-only until `calibration` Brier < 0.24 on a real sample AND positive
  paper PnL after costs.
- Live requires `TRADING_MODE=live` + `LIVE_CONFIRM=I_UNDERSTAND_THE_RISK` +
  the calibration gate.
- Margin only after live proves out, incrementally (start 1.2x, never 2x).
- Per-trade risk cap, exposure cap, daily loss circuit breaker, LIMIT-only.

See RESEARCH_AND_PLAN.md, TRADING_STRATEGY.md, DATA_FEEDS.md for the reasoning.
