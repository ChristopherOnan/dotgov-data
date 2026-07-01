# AetherCouncil — the self-improving loop

Goal: an autonomous system that gets **better at capitalizing on daily market
moves the longer it runs**, without human retraining. This is built on the
current research consensus for LLM agents (citations at the bottom), adapted to
a risk-first trading system.

## The loop

```
        ┌───────────────────────── LEARN ──────────────────────────┐
        │                                                           │
   SENSE ──▶ DECIDE ──▶ ACT ──▶ SCORE ──▶ REFLECT ──▶ (adjust) ─────┘
   data       agents    paper   outcome   rules/weights/memory
```

Every stage now has a feedback path, so measured outcomes change future
behavior. Nothing is fine-tuned — improvement is **verbal reinforcement
learning** (learning stored as text/weights the agents read next time).

## The five mechanisms (and where they live)

1. **Verified data — `data_guard.py`** (garbage-in defense)
   Cross-source (Finnhub vs Yahoo) + history-plausibility + volume corroboration.
   Bad ticks (a 10x split artifact, a wrong-symbol print) are rejected before
   they can drive a trade or, worse, teach the system a false lesson. Adding the
   free `FINNHUB_API_KEY` turns on true cross-source triangulation.

2. **Episodic memory — `memory.py`** (learn from your own history)
   Every decision is stored with the market features that produced it and its
   eventual outcome. Before a new decision, the most *similar* past setups are
   recalled and injected into the prompt: "the last 5 oversold bounces on this
   kind of name went 1/5 — be careful." This is FinMem/Reflexion's memory core.

3. **Per-agent skill weighting — `agent_scorecard.py`** (trust who earns it)
   Each model's individual probability is logged per decision and scored (Brier)
   when the trade resolves. Consensus becomes **skill-weighted**: proven
   forecasters count more, anti-correlated ones get driven toward zero weight.
   Low-sample models are shrunk toward equal weight so a lucky streak can't
   hijack the vote. (OPTAGENT-style meta-learning.)

4. **Reflection → reusable rules — `reflection.py`** (the learning step)
   Nightly, a reflection agent reads the track record, calibration, scorecard,
   and memory, writes an honest assessment, and distills **concrete, testable
   rules** ("sub-0.65 setups all lost — treat as no-trade"). Rules persist
   (capped, deduped, human-reviewable) and are injected into every future
   deliberation. (Reflexion + Meta-Policy Reflexion's reusable rule memory.)

5. **Proof-of-edge gate — `portfolio.py` + `calibration.py`** (don't fool yourself)
   The loop only earns real money once the paper track record clears the gate:
   ≥20 closed trades, Brier < 0.24, positive PnL after costs. Self-improvement
   is measured, not assumed.

6. **Parameter self-tuning — `tuner.py` + `params.py`** (adapt to drift, don't overfit)
   Weekly, the RSI thresholds / stop distance / hold are re-searched on recent
   data — but nothing is adopted unless it beats the current settings ON A
   HELD-OUT WINDOW it wasn't tuned on, is positive out of sample, and has enough
   validation trades. Overfit settings die at the validation gate (observed live:
   a +23% in-sample combo earned -3.6% out of sample and was correctly rejected).
   Validated params land in params.json and are read live via params.py.

## How it flows through a single trade

1. `data_guard` verifies the price.
2. `memory.recall()` + `reflection.active_rules()` are injected into
   `agent_pool.deliberate()` as context.
3. The swarm (and gated council) vote; consensus is **skill-weighted** by
   `agent_scorecard`.
4. If it clears the entry bar, `portfolio` opens a paper position and we record
   the episode (`memory`) and every model's vote (`agent_scorecard`).
5. When the position hits stop/target/time, `portfolio` resolves it and books
   the true outcome into `calibration`, `memory`, and `agent_scorecard` at once.
6. Nightly, `reflection` turns the accumulated outcomes into updated rules and
   the scorecard re-weights the agents. The system that trades tomorrow is
   literally not the one that traded today.

## Sub-agents (dynamic depth) — `subagents.py`
When a decision is genuinely hard, a lead agent can build its own specialists
(technicals / catalysts / sector), gather their findings, and synthesize —
bounded by depth, fan-out, and a shared budget so it can never run away.

## Daily research — `daily_scout.py`
Separately, scanner agents scan X/web daily for new models, tools, and
strategies; a curator ranks them ADOPT/TEST/WATCH. This improves the *system*,
not just the trades (e.g., it's how we'd learn a cheaper/better model shipped).

## Operate it
```bash
python3 run_loop.py --reflect   # run the learning step now, print active rules
python3 run_loop.py --track     # track record + live-gate status
python3 run_loop.py --picks     # best stocks now (uses memory + rules + weights)
python3 run_loop.py             # always-on: trade loop + nightly reflect + scout
```

## Research this is built on
- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (arXiv:2303.11366)
- Yu et al., *FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory* (arXiv:2311.13743)
- *TradingAgents: Multi-Agents LLM Financial Trading Framework* (arXiv:2412.20138)
- *Meta-Policy Reflexion: Reusable Reflective Memory and Rule Admissibility* (arXiv:2509.03990)
- *OPTAGENT: Optimizing Multi-Agent LLM Interactions via Verbal RL* (arXiv:2510.18032)
- Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback*
```
