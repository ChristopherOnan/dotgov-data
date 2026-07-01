# AetherCouncil autonomous trading — first-principles design

## 1. The edge, stated correctly
- Historically ~all of the market's long-run gain accrued OVERNIGHT (close→open),
  not intraday. But: (a) that's about HOLDING through the gap, not day-trading
  the thin after-hours tape; (b) naive nightly churn is killed by spreads/costs.
- Durable, capacity-limited edges that need after-hours access:
  1. Overnight POSITIONING of high-quality setups (hold through the gap).
  2. CATALYST REACTION — news after close (earnings, M&A like RKLB/Iridium)
     acted on before the open crowd.
- We do NOT scalp illiquid extended-hours tape. Limit orders only, ever.

## 2. What kills us (engineer this out first)
Ruin. Being right on average but wiped by one leveraged gap. Therefore:
- Risk per trade capped at a small fixed fraction of equity (default 0.75%).
- Position size derived FROM the stop distance, not chosen arbitrarily.
- Daily loss circuit breaker (default -3% halts new entries for the day).
- Max concurrent positions + max gross exposure caps.
- Extended/overnight: LIMIT orders with a max-slippage guard. Never market
  into thin books.
- Margin is EARNED: only after a paper track record clears the calibration
  gate, and then capped well below max (start 1.2x, never jump to 2x).
- Hard kill switch + live-trading disabled by default.

## 3. Broker
Alpaca (official API, 24/5, paper trading, extended hours native, same data
source as market_context.py). Robinhood has no official stocks API; its
unofficial wrapper is the fragility that caused the pulse OSError. If Robinhood
execution is wanted later, hide it behind the same OrderRouter interface and
validate on Alpaca paper first.

## 4. Token-cost calibration (spend tokens on DECISIONS, not WATCHING)
First principle: monitoring is free (Python); judgment costs tokens. So:
- Tier 0 — WATCHER (free, no LLM): poll quotes, detect setups via rules
  (overnight gap, catalyst move, volume spike, ATR breakout). 99% of cycles
  end here at $0.
- Tier 1 — SWARM (cheap, ~$0.002): only on a triggered setup, cheap models
  vote (agent_pool.run_swarm).
- Tier 2 — EXPERT COUNCIL (Claude/Grok/Gemini, ~$0.005, GATED): only when the
  swarm disagrees or hits high conviction AND the opportunity is large enough
  to justify frontier tokens.
- Never re-deliberate an open position without a NEW trigger. Cache. Daily
  token budget cap. Spend proportional to opportunity size.
Result: a day of watching hundreds of ticks might cost pennies, because tokens
are spent only at the moment of decision.

## 5. Validation gate (no real money until this passes)
- Run PAPER for a meaningful sample of trades.
- Log every call to calibration.py; require Brier < 0.24 (beats coin flip)
  AND positive paper PnL after modeled costs AND max drawdown within limit.
- Only then flip TRADING_MODE=live, small size.
- Only after live proves out do we enable margin, incrementally.

## 6. Build order
1. trading_engine.py scaffold (Alpaca paper, risk manager, watcher, LLM-gated
   decisions, calibration logging).  [built]
2. Paper-trade + collect calibration data.
3. Tune watcher thresholds + escalation gates against results.
4. Gate check → tiny live → (later) incremental margin.

## Sources
- Overnight anomaly: https://arxiv.org/pdf/2010.01727 ,
  https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/
- Alpaca 24/5: https://alpaca.markets/blog/introducing-stocks-24_5-overnight-with-alpaca-trading-api/
- Robinhood API status: https://www.bitget.com/wiki/does-robinhood-allows-api-based-trading-for-stocks
