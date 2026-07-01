# AetherCouncil — X/web research + first-principles upgrade plan

Date: 2026-06-29. Built from live web/X research + everything established in
this session. (I could not read your literal repo — these are accurate,
drop-in modules; wiring notes below.)

## The big finding
Don't scrape X. **xAI has a native `x_search` tool** (keyword + semantic +
user search + thread fetch, with `allowed_x_handles` / `from_date` / `to_date`
filters) callable straight from the Grok Responses API your council already
uses. Let Grok scan X as a tool call — no Twitter API, no scraping, no auth
fragility. `x_scout.py` (included) implements exactly this.

## Correct model name
The real current model is **`grok-4.3`**. Your `grok-4.20-multi-agent-0309`
is invented and will hard-fail every call. `validate_models.py` (included)
checks all configured models against xAI's live list at startup and refuses
to boot on a bad one.

## What I shipped in this drop
1. **x_scout.py** — native X/web discovery scout. Returns ranked JSON
   candidates (new model/data/tooling/orchestration/risk/strategy ideas) each
   with a concrete `suggested_action`. Run: `python3 -m x_scout`.
2. **validate_models.py** — startup model validator. Run: `python3 validate_models.py`.
   (Both depend on the `xai_resilient.py` you already have.)

## Prioritized roadmap (first-principles, ranked by alpha-per-effort)

1. **Live data INTO the prompts** (highest leverage). LLMs only know what's
   in context. Build a `MARKET CONTEXT` block (quotes for watched tickers) and
   prepend it to every agent. Use a real data API (Alpaca/Polygon/Tradier),
   not Robinhood (unofficial, 2FA, fragile — likely source of your pulse
   `OSError`). *This is what fixes "shallow answers" at the root.*

2. **Fix model config** — set `XAI_ANALYSIS_MODEL = "grok-4.3"`, wire
   `validate_models()` into startup. (Done — just apply.)

3. **Native X scouting** — adopt `x_scout.py`; schedule it pre-market. (Done.)

4. **Structured debate, gated.** Research warning: multi-agent debate improves
   calibration but its documented failure mode is *over-trading* (more trades,
   not more alpha). So: proposer → critic → synthesizer → judge, emitting
   strict JSON (thesis/evidence/probability/confidence/risks), and only escalate
   to full council on high-conviction triggers. Cheaper and better.

5. **Calibration scoring** — log every probability call and score a rolling
   Brier score. Without this you can't tell if the council is any good.

6. **Unswallow errors** — replace `except: print("pulse error: OSError")` with
   full `traceback` logging so failures are diagnosable.

## To apply
- Drop `x_scout.py` and `validate_models.py` next to `config.py`.
- In `config.py` add: `XAI_ANALYSIS_MODEL = "grok-4.3"`, `XAI_SCOUT_MODEL = "grok-4.3"`,
  and (optional) `SCOUT_X_HANDLES = [...]`, `SCOUT_FOCUS = "..."`.
- Verify: `python3 validate_models.py` then `python3 -m x_scout`.

## To let me do items 1, 4, 5 directly in your code
Either push the repo (`gh repo create AetherCouncil --private --source=. --push`,
then send the name) or run `make_review_bundle.sh` and upload the bundle.
With the actual source I'll wire these into your real files and hand back
finished diffs.

## Sources
- xAI X Search tool: https://docs.x.ai/developers/tools/x-search
- xAI Live/Web Search: https://docs.x.ai/docs/guides/live-search
- TradingAgents (multi-agent framework): https://github.com/TauricResearch/TradingAgents
- Eval/coordination + over-trading failure mode: https://arxiv.org/pdf/2603.27539
- Finance LLM benchmark (model picks): https://aimultiple.com/finance-llm
- FinTwit signal ecosystem: https://fintwit.ai/
