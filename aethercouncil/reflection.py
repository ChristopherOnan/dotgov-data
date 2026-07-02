"""
reflection.py — the learning step that closes the self-improvement loop.

Sense -> Decide -> Act -> Score -> **REFLECT -> adjust** -> repeat.

Nightly, a reflection agent reads everything the system now knows about itself —
closed paper trades, calibration (Brier), per-agent skill scores, and episodic
memory hit-rates — and does two things (Reflexion + Meta-Policy Reflexion):
  1. writes a short verbal reflection on what's working and what isn't, and
  2. distills that into a small set of REUSABLE, concrete trading RULES.

Those rules are persisted (human-reviewable, capped, deduped) and injected into
future deliberations via active_rules(), so the agents actually change behavior
based on measured outcomes — not vibes. This is verbal reinforcement learning:
improvement without any fine-tuning.

    import reflection
    await reflection.reflect()          # nightly: learn + update rules
    ctx = reflection.active_rules()     # inject into decision prompts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

log = logging.getLogger("aethercouncil.reflection")

RULES_PATH = os.getenv("RULES_PATH", "rules.json")
MAX_RULES = int(os.getenv("MAX_RULES", "12"))
REFLECT_MODEL = os.getenv("REFLECT_MODEL", "anthropic/claude-sonnet-5")


def _load_rules() -> list[dict]:
    try:
        with open(RULES_PATH) as f:
            return json.load(f).get("rules", [])
    except Exception:  # noqa: BLE001
        return []


def _save_rules(rules: list[dict]) -> None:
    try:
        with open(RULES_PATH, "w") as f:
            json.dump({"updated": datetime.now(timezone.utc).isoformat(),
                       "rules": rules[:MAX_RULES]}, f, indent=2)
    except Exception as e:  # noqa: BLE001
        log.warning("rules save failed: %s", e)


def active_rules() -> str:
    """Prompt-ready block of learned rules (empty string if none yet)."""
    rules = _load_rules()
    if not rules:
        return ""
    lines = ["LEARNED RULES (from our own tracked outcomes — follow unless clearly wrong):"]
    lines += [f"- {r['rule']}" for r in rules[:MAX_RULES]]
    return "\n".join(lines)


def _gather_evidence() -> str:
    """Collect the system's self-knowledge into one evidence blob."""
    parts = []
    try:
        from portfolio import Portfolio
        pf = Portfolio()
        parts.append(pf.track_record_str())
        closed = [p for p in pf.positions if p.status == "closed"][-20:]
        if closed:
            parts.append("RECENT CLOSED TRADES:")
            for p in closed:
                parts.append(f"- {p.symbol} entry {p.entry} exit {p.exit_price} "
                             f"({p.exit_reason}) ret {(p.ret or 0)*100:+.1f}% prob {p.prob}")
    except Exception as e:  # noqa: BLE001
        parts.append(f"(portfolio unavailable: {e})")
    try:
        import agent_scorecard
        parts.append(agent_scorecard.report())
    except Exception:  # noqa: BLE001
        pass
    try:
        import memory
        parts.append(f"MEMORY: {memory.stats()}")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


_SYS = (
    "You are the reflection module of an autonomous trading system. You are given "
    "the system's OWN tracked performance. Think from first principles and be "
    "brutally honest. Identify what is actually working and what is losing money, "
    "then distill CONCRETE, ACTIONABLE rules the traders should follow next. Rules "
    "must be specific and testable (reference setups, RSI levels, sectors, sizing, "
    "or which agents to trust), not platitudes. Avoid health/pharma and crypto."
)

_TMPL = (
    "SYSTEM PERFORMANCE EVIDENCE:\n{evidence}\n\n"
    "Return ONLY JSON:\n"
    '{{"reflection":"2-3 sentence honest assessment",'
    '"rules":["concrete rule 1","concrete rule 2", ...]}}\n'
    "Give at most 8 rules, ranked most important first. If evidence is too thin "
    "to conclude anything, return few or no rules rather than guessing."
)


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


async def reflect() -> dict:
    """Run one reflection pass: learn from outcomes, update the rule set."""
    evidence = _gather_evidence()
    try:
        from agent_pool import make_client, ask, ModelSpec, Ledger
        client = make_client()
        ledger = Ledger()
        spec = ModelSpec("reflector", REFLECT_MODEL, "council")
        r = await ask(client, spec, _SYS, _TMPL.format(evidence=evidence), ledger,
                      max_tokens=900)
        data = _extract_json(r.get("text") or "")
    except Exception as e:  # noqa: BLE001
        log.error("reflection call failed: %s", e)
        return {"error": str(e)}

    new_rules = [str(x).strip() for x in data.get("rules", []) if str(x).strip()]
    if new_rules:
        # merge: keep newest, dedupe by lowercase text, cap
        now = datetime.now(timezone.utc).isoformat()
        merged = [{"rule": rr, "added": now} for rr in new_rules]
        seen = {rr.lower() for rr in new_rules}
        for old in _load_rules():
            if old["rule"].lower() not in seen:
                merged.append(old)
                seen.add(old["rule"].lower())
        _save_rules(merged)
    log.info("reflection: %d rules now active", len(_load_rules()))
    return {"reflection": data.get("reflection", ""),
            "rules": [r["rule"] for r in _load_rules()],
            "cost_usd": round(ledger.spent, 6)}


def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = asyncio.run(reflect())
    if out.get("error"):
        print("reflection failed:", out["error"]); return
    print("REFLECTION:", out.get("reflection", ""))
    print("\nACTIVE RULES:")
    for r in out.get("rules", []):
        print(" -", r)


if __name__ == "__main__":
    _cli()
