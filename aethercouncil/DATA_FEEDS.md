# Market data + real-time TA — first-principles verdict

## TL;DR
Don't buy indicators — compute them from ONE free real-time price stream.
Skip dark pools for intraday. For 5–10 trades/day you don't need HFT data.
Keep the fast (timing) loop LLM-free; spend tokens only to pick setups.

## 1. Data feeds (free, 2026)
| Use | Pick | Why |
|---|---|---|
| Stocks real-time | **Finnhub** free WS (<100ms) &/or **Alpaca** IEX free | Finnhub = broad real-time trades free; Alpaca = data+execution in one |
| Stocks full-market (later) | Alpaca SIP (~$99/mo) | Only if IEX/Finnhub coverage proves limiting |
| Crypto real-time 24/7 | **Binance/Coinbase/Alpaca(Kraken)** public WS, free, no auth | True round-the-clock + best free realtime |
| Fundamentals/quotes | Finnhub / Yahoo (already wired) | Free |

**Crypto insight:** your goal (frequent, round-the-clock trades on free data)
fits CRYPTO far better than stocks — stocks are 24/5 and free real-time is
thinner. Strongly consider crypto for the fast-frequent style.

## 2. Dark pools — honest take (skip for intraday)
- Free FINRA ATS data is delayed ~2 weeks; real-time is paid ($50–200/mo).
- Free dark-pool data suits SWING/POSITION trading, not 5–10 trades/day.
- For your cadence it's marketing, not alpha. At most use weekly ATS
  accumulation as slow context — never for entry timing.

## 3. Technical analysis — compute, don't buy
RSI/MACD/VWAP are deterministic functions of price. Computing locally is
faster (no round trip), free, and unlimited. `stream_indicators.py` does this
incrementally (O(1)/tick) and its RSI matches the batch reference EXACTLY.

## 4. The latency chain that matters (for 5–10 trades/day)
feed (tens of ms — fine)  ->  indicator compute (microseconds, local)
->  DECISION (the slow/expensive part)  ->  execution (fill quality = real cost)

Therefore:
- FAST LOOP (free, no LLM): stream -> LiveTA -> rule signals (RSI cross, VWAP
  reclaim, MACD). Handles optimal entry/exit TIMING in microseconds.
- DECISION LOOP (LLM, gated): agent_pool picks WHICH signals to arm + sizing
  conviction — not per-tick timing.
- EXECUTION: LIMIT orders only (trading_engine), esp. extended/overnight.

## 5. How the pieces connect
finnhub_stream.py  ──trades──▶  stream_indicators.LiveTA  ──signal──▶
   agent_pool.deliberate (gated)  ──action──▶  trading_engine (risk + LIMIT order)
   ──▶ calibration.py (score every call, tune thresholds)

## 6. Build status
- stream_indicators.py — DONE + tested (RSI exact vs reference).
- finnhub_stream.py — DONE (thin glue; needs FINNHUB_API_KEY + `websockets`).
- Next: on_signal handler that gates to agent_pool and sizes via trading_engine;
  a crypto WS adapter (same shape) if you go the 24/7 route.

## Sources
- Free real-time APIs: https://finnhub.io/docs/api/websocket-trades ,
  https://alpaca.markets/data
- Dark pool reality: https://meridianfin.io/knowledge/free-dark-pool-data ,
  https://otctransparency.finra.org/otctransparency/
- Compute-your-own TA: https://github.com/TA-Lib/ta-lib-python ,
  https://github.com/mr-easy/streaming_indicators
- Free crypto WS: https://www.coingecko.com/learn/top-5-best-crypto-websocket-apis
