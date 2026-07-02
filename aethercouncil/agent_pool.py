"""
agent_pool.py — cost-optimal agent army for AetherCouncil (via OpenRouter).

Strategy (your goal: max quality per token, never a surprise bill):

  TIER 1 — SWARM (cheap Chinese/OSS models, run in PARALLEL)
     Does all the breadth work: per-ticker analysis, scouting, criticism.
     ~$0.06–0.50 / 1M tokens. This is where 95% of tokens are spent.

  TIER 2 — EXPERT COUNCIL (Claude + Grok + Gemini), GATED
     Only fires when the swarm DISAGREES (high spread) or reaches HIGH
     CONVICTION. Frontier tokens are 10–100x pricier, so we spend them
     rarely, on the calls that actually matter.

Cost safety:
  • Every call's real cost is read from OpenRouter's usage.cost and summed.
  • BUDGET_PER_RUN hard-caps a deliberation; the council is skipped (not the
    whole run) if it would blow the cap — so you degrade gracefully instead
    of being forced to permanently downgrade Claude.
  • Optional short-TTL disk cache avoids paying twice for identical prompts.

Setup:  export OPENROUTER_API_KEY=...   (pip install openai)
Test :  python3 agent_pool.py --list
        python3 agent_pool.py "RKLB upside this week given the Iridium deal?"
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Optional

from openai import (
    AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError,
)

log = logging.getLogger("aethercouncil.pool")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 5

# ---- cost + gating knobs (override via env) --------------------------------
BUDGET_PER_RUN = float(os.getenv("BUDGET_PER_RUN", "0.25"))   # USD hard cap
CACHE_TTL = int(os.getenv("AGENT_CACHE_TTL", "600"))          # seconds; 0=off
CACHE_DIR = os.getenv("AGENT_CACHE_DIR", ".agent_cache")
DIVERGENCE_THRESH = float(os.getenv("DIVERGENCE_THRESH", "0.22"))  # prob stdev
CONVICTION_THRESH = float(os.getenv("CONVICTION_THRESH", "0.20"))  # |mean-0.5|

# ---- model registry (verified slugs, June 2026) ----------------------------
@dataclass
class ModelSpec:
    role: str
    model: str
    tier: str  # "swarm" | "council"

SWARM: list[ModelSpec] = [
    ModelSpec("deepseek", os.getenv("OR_DEEPSEEK", "deepseek/deepseek-v4-flash"), "swarm"),
    ModelSpec("glm",      os.getenv("OR_GLM",      "z-ai/glm-4.7-flash"),         "swarm"),
    ModelSpec("minimax",  os.getenv("OR_MINIMAX",  "minimax/minimax-m2.5"),       "swarm"),
    ModelSpec("qwen",     os.getenv("OR_QWEN",     "qwen/qwen3-30b-a3b-instruct-2507"), "swarm"),
]
# Your expert trio for high-level decisions. Escalate Claude to opus-4.8 anytime.
COUNCIL: list[ModelSpec] = [
    ModelSpec("claude", os.getenv("OR_CLAUDE", "anthropic/claude-sonnet-5"), "council"),
    ModelSpec("grok",   os.getenv("OR_GROK",   "x-ai/grok-4.3"),             "council"),
    ModelSpec("gemini", os.getenv("OR_GEMINI", "google/gemini-3.1-flash-lite"), "council"),
]


@dataclass
class Ledger:
    """Tracks spend across a deliberation."""
    spent: float = 0.0
    calls: list[dict] = field(default_factory=list)
    def add(self, model: str, cost: float, tokens: int) -> None:
        self.spent += cost
        self.calls.append({"model": model, "cost": cost, "tokens": tokens})
    def would_exceed(self, budget: float) -> bool:
        return self.spent >= budget


def make_client() -> AsyncOpenAI:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE, timeout=120.0,
                       max_retries=0, default_headers={"X-Title": "AetherCouncil"})


def _retryable(e: Exception) -> bool:
    if isinstance(e, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    return isinstance(e, APIStatusError) and e.status_code in _RETRYABLE


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, key + ".json")


def _cache_get(key: str) -> Optional[str]:
    if CACHE_TTL <= 0:
        return None
    p = _cache_path(key)
    try:
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < CACHE_TTL:
            return json.load(open(p))["text"]
    except Exception:  # noqa: BLE001
        return None
    return None


def _cache_put(key: str, text: str) -> None:
    if CACHE_TTL <= 0 or text is None:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        json.dump({"text": text}, open(_cache_path(key), "w"))
    except Exception:  # noqa: BLE001
        pass


def _usage_cost(resp: Any) -> tuple[float, int]:
    """Pull OpenRouter's real cost + total tokens from the response."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0.0, 0
    cost = getattr(u, "cost", None)
    if cost is None:
        extra = getattr(u, "model_extra", None) or {}
        cost = extra.get("cost", 0.0)
    return float(cost or 0.0), int(getattr(u, "total_tokens", 0) or 0)


async def ask(client: AsyncOpenAI, spec: ModelSpec, system: str, user: str,
              ledger: Ledger, max_tokens: int = 1200) -> dict[str, Any]:
    ck = hashlib.sha256(f"{spec.model}|{system}|{user}".encode()).hexdigest()[:32]
    cached = _cache_get(ck)
    if cached is not None:
        return {"role": spec.role, "model": spec.model, "text": cached,
                "ok": True, "cached": True}

    last: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.chat.completions.create(
                model=spec.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content
            cost, toks = _usage_cost(resp)
            ledger.add(spec.model, cost, toks)
            if not text:  # empty completion (some providers hiccup)
                raise ValueError("empty completion")
            _cache_put(ck, text)
            return {"role": spec.role, "model": spec.model, "text": text,
                    "ok": True, "cost": cost, "cached": False}
        except Exception as e:  # noqa: BLE001
            last = e
            if not _retryable(e) or attempt == _MAX_ATTEMPTS:
                break
            d = min(2.0 * 2 ** (attempt - 1), 16.0)
            await asyncio.sleep(d + random.uniform(0, d * 0.25))
    log.warning("agent %s failed: %s", spec.role, last)
    return {"role": spec.role, "model": spec.model, "text": None,
            "ok": False, "error": repr(last)}


_WORKER_SYS = (
    "You are a market-research worker on the Aether Council. Reason from first "
    "principles, cite the live numbers/news you use, be terse. Your LAST line "
    "must follow this exact shape (fill in real values, keep the keywords):\n"
    "STANCE=bullish PROB=0.62 RISK=one short clause\n"
    "STANCE must be one of bullish/bearish/neutral and PROB a decimal 0..1."
)

_PROB_RE = re.compile(r"PROB\s*=\s*([01](?:\.\d+)?)", re.I)


def _probs(results: list[dict]) -> list[float]:
    out = []
    for r in results:
        if r["ok"] and r["text"]:
            m = _PROB_RE.search(r["text"])
            if m:
                try:
                    out.append(max(0.0, min(1.0, float(m.group(1)))))
                except ValueError:
                    pass
    return out


async def run_swarm(client, task, ctx, ledger) -> list[dict]:
    user = (ctx + "\n\n" if ctx else "") + task
    res = await asyncio.gather(*(ask(client, s, _WORKER_SYS, user, ledger) for s in SWARM))
    log.info("swarm: %d/%d ok, spent $%.5f", sum(r["ok"] for r in res), len(SWARM), ledger.spent)
    return list(res)


def _should_escalate(probs: list[float]) -> tuple[bool, str]:
    if len(probs) < 2:
        return True, "insufficient swarm signal"
    spread = pstdev(probs)
    conviction = abs(mean(probs) - 0.5)
    if spread >= DIVERGENCE_THRESH:
        return True, f"swarm disagreement (stdev={spread:.2f})"
    if conviction >= CONVICTION_THRESH:
        return True, f"high conviction (mean={mean(probs):.2f})"
    return False, f"swarm consensus, low stakes (stdev={spread:.2f})"


_COUNCIL_SYS = (
    "You are an expert member of the Aether Council making a HIGH-LEVEL call. "
    "You are given a diverse worker swarm's analyses. Weigh them critically, "
    "add your own edge. Your LAST line must follow this exact shape (fill in "
    "real values, keep the keywords):\n"
    "STANCE=bullish PROB=0.62 ACTION=no-trade; conviction too low for size\n"
    "STANCE must be one of bullish/bearish/neutral and PROB a decimal 0..1."
)


async def run_council(client, task, swarm, ledger) -> list[dict]:
    panel = "\n\n".join(f"[{r['role']}] {r['text']}" for r in swarm if r["ok"] and r["text"])
    user = f"TASK: {task}\n\nSWARM PANEL:\n{panel}"
    out = []
    for spec in COUNCIL:
        if ledger.would_exceed(BUDGET_PER_RUN):
            log.warning("budget $%.2f hit — skipping %s", BUDGET_PER_RUN, spec.role)
            out.append({"role": spec.role, "model": spec.model, "ok": False,
                        "error": "budget_cap"})
            continue
        out.append(await ask(client, spec, _COUNCIL_SYS, user, ledger, max_tokens=900))
    return out


def _votes(results: list[dict]) -> dict[str, float]:
    """Map model slug -> its parsed probability (for skill scoring)."""
    out: dict[str, float] = {}
    for r in results:
        if r["ok"] and r["text"]:
            m = _PROB_RE.search(r["text"])
            if m:
                try:
                    out[r["model"]] = max(0.0, min(1.0, float(m.group(1))))
                except ValueError:
                    pass
    return out


def _learned_context() -> str:
    """Self-improvement context: learned rules + the council's shared blackboard.
    Kept compact on purpose — this is prepended to EVERY deliberation, so every
    line here costs tokens on every call."""
    parts = []
    try:
        from reflection import active_rules
        r = active_rules()
        if r:
            parts.append(r)
    except Exception:  # noqa: BLE001
        pass
    try:
        from journal import recent
        j = recent()
        if j:
            parts.append(j)
    except Exception:  # noqa: BLE001
        pass
    return "\n\n".join(parts)


async def deliberate(task: str, tickers: list[str] | None = None,
                     extra_context: str = "") -> dict[str, Any]:
    client = make_client()
    ledger = Ledger()
    ctx_parts = []
    if tickers:
        try:
            from market_context import build_market_context
            ctx_parts.append(await asyncio.to_thread(build_market_context, tickers))
        except Exception as e:  # noqa: BLE001
            log.warning("no market context: %s", e)
    # inject learned rules (reflection) + caller-supplied memory recall
    rules = _learned_context()
    if rules:
        ctx_parts.append(rules)
    if extra_context:
        ctx_parts.append(extra_context)
    ctx = "\n\n".join(p for p in ctx_parts if p)

    swarm = await run_swarm(client, task, ctx, ledger)
    escalate, reason = _should_escalate(_probs(swarm))
    council = await run_council(client, task, swarm, ledger) if escalate else []

    votes = _votes(council) if council else _votes(swarm)
    # skill-weighted consensus (falls back to equal weight until we have history)
    try:
        from agent_scorecard import weighted_consensus
        consensus = weighted_consensus(votes)
    except Exception:  # noqa: BLE001
        consensus = round(mean(votes.values()), 4) if votes else None
    return {
        "task": task,
        "escalated": escalate,
        "gate_reason": reason,
        "swarm": [{"role": r["role"], "text": r["text"], "ok": r["ok"]} for r in swarm],
        "council": [{"role": r["role"], "text": r.get("text"), "ok": r["ok"]} for r in council],
        "consensus_prob": round(consensus, 3) if consensus is not None else None,
        "votes": votes,
        "cost_usd": round(ledger.spent, 6),
        "calls": ledger.calls,
    }


async def list_models() -> list[str]:
    client = make_client()
    return sorted(getattr(m, "id", str(m)) for m in (await client.models.list()).data)


def _cli() -> None:
    import sys
    logging.basicConfig(level=logging.INFO)
    args = sys.argv[1:]
    if args and args[0] == "--list":
        print("\n".join(asyncio.run(list_models())))
        return
    task = " ".join(args) or "Assess RKLB upside this week."
    out = asyncio.run(deliberate(task, tickers=["RKLB", "ASTS", "ACHR"]))
    print(json.dumps(out, indent=2))
    print(f"\n>>> escalated={out['escalated']} ({out['gate_reason']}) "
          f"consensus_prob={out['consensus_prob']} cost=${out['cost_usd']}")


if __name__ == "__main__":
    _cli()
