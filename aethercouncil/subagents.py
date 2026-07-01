"""
subagents.py — let an agent build and manage its own sub-agents, safely.

First principles: a strong analyst decomposes. When a task is genuinely hard, the
best move is to spin up focused specialists (a technicals sub-agent, a catalysts
sub-agent, a sector-context sub-agent), let each go deep, then synthesize. This
gives the swarm dynamic depth without a human pre-wiring every role.

The risk with self-spawning agents is unbounded cost and infinite recursion. So
this orchestrator is hard-bounded on three axes, all sharing ONE budget ledger:
  • MAX_DEPTH       — how many levels of sub-agents (default 2)
  • MAX_SUBAGENTS   — fan-out per level (default 4)
  • SUBAGENT_BUDGET — total USD across the whole tree (hard cap)

A lead agent decides FOR ITSELF whether to spawn. If it can answer directly, it
does (cheap). If it needs help, it emits a spawn plan; we run those specialists
(which may themselves spawn, until MAX_DEPTH), then the lead synthesizes. Every
call's real cost is metered; spawning stops the instant the budget is threatened.

    from subagents import orchestrate
    out = await orchestrate("Assess RKLB for an overnight long.", tickers=["RKLB"])
    print(out["answer"]); print("cost $", out["cost_usd"]); print(out["tree"])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

from agent_pool import Ledger, ModelSpec, SWARM, COUNCIL, ask, make_client

log = logging.getLogger("aethercouncil.subagents")

MAX_DEPTH = int(os.getenv("SUBAGENT_MAX_DEPTH", "2"))
MAX_SUBAGENTS = int(os.getenv("SUBAGENT_MAX_FANOUT", "4"))
SUBAGENT_BUDGET = float(os.getenv("SUBAGENT_BUDGET", "0.15"))   # USD, whole tree
LEAD_MODEL = os.getenv("SUBAGENT_LEAD", SWARM[0].model)         # cheap by default
WORKER_MODEL = os.getenv("SUBAGENT_WORKER", SWARM[0].model)

_SPAWN_RE = re.compile(r"\{[^{}]*\"spawn\"\s*:\s*\[.*?\]\s*\}", re.DOTALL)


def _lead_sys(depth: int, can_spawn: bool) -> str:
    base = (
        "You are a lead analyst on the Aether Council. Reason from first "
        "principles and be terse. "
    )
    if can_spawn:
        return base + (
            "If — and only if — the task genuinely needs decomposition, you MAY "
            "build sub-agents to investigate parts in parallel. To do so, emit a "
            "SINGLE json object on its own line:\n"
            '{"spawn":[{"role":"short-name","task":"focused question"}, ...]}\n'
            f"Spawn at most {MAX_SUBAGENTS}, only when it clearly improves the "
            "answer (extra agents cost money). If you can answer well directly, "
            "do NOT spawn — just answer. After you receive sub-agent findings, "
            "synthesize ONE decisive answer."
        )
    return base + ("Answer directly and decisively; you cannot spawn further "
                   "sub-agents at this depth.")


def _parse_spawn(text: str) -> list[dict]:
    if not text:
        return []
    m = _SPAWN_RE.search(text)
    if not m:
        return []
    try:
        plan = json.loads(m.group(0)).get("spawn", [])
    except json.JSONDecodeError:
        return []
    out = []
    for s in plan[:MAX_SUBAGENTS]:
        if isinstance(s, dict) and s.get("task"):
            out.append({"role": str(s.get("role", "worker"))[:24], "task": str(s["task"])})
    return out


async def orchestrate(task: str, context: str = "", *, tickers: Optional[list[str]] = None,
                      depth: int = 0, ledger: Optional[Ledger] = None,
                      budget: float = SUBAGENT_BUDGET, client=None) -> dict[str, Any]:
    """Run a lead agent that may build+manage sub-agents, within hard caps."""
    ledger = ledger if ledger is not None else Ledger()
    client = client or make_client()

    # market context on the top-level call only
    if tickers and depth == 0 and not context:
        try:
            from market_context import build_market_context
            context = await asyncio.to_thread(build_market_context, tickers)
        except Exception as e:  # noqa: BLE001
            log.warning("no market context: %s", e)

    can_spawn = depth < MAX_DEPTH and not ledger.would_exceed(budget)
    lead = ModelSpec("lead", LEAD_MODEL, "swarm")
    user = (context + "\n\n" if context else "") + task
    r = await ask(client, lead, _lead_sys(depth, can_spawn), user, ledger)
    answer = r.get("text") or ""

    plan = _parse_spawn(answer) if can_spawn else []
    tree: list[dict] = []
    if plan:
        log.info("depth %d: lead spawns %d sub-agent(s) %s", depth,
                 len(plan), [p["role"] for p in plan])
        # run specialists in parallel; each may recurse until MAX_DEPTH/budget
        async def _run(p):
            if ledger.would_exceed(budget):
                return {"role": p["role"], "answer": "(skipped: budget)", "cost_usd": 0.0}
            sub = await orchestrate(p["task"], depth=depth + 1, ledger=ledger,
                                    budget=budget, client=client)
            return {"role": p["role"], "answer": sub["answer"], "tree": sub.get("tree", [])}
        tree = await asyncio.gather(*(_run(p) for p in plan))

        # lead synthesizes from sub-agent findings
        findings = "\n\n".join(f"[{t['role']}] {t['answer']}" for t in tree)
        syn = await ask(client, lead,
                        "You are the lead analyst. Synthesize your sub-agents' "
                        "findings into ONE decisive, first-principles answer. Be terse.",
                        f"TASK: {task}\n\nSUB-AGENT FINDINGS:\n{findings}", ledger)
        answer = syn.get("text") or answer

    return {"task": task, "depth": depth, "answer": answer,
            "spawned": len(plan), "tree": tree,
            "cost_usd": round(ledger.spent, 6)}


def _cli() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    task = " ".join(a for a in sys.argv[1:] if not a.startswith("-")) or \
        "Assess RKLB for an overnight long: weigh technicals, catalysts, and sector."
    out = asyncio.run(orchestrate(task, tickers=["RKLB"]))
    print("\n=== ANSWER ===\n" + out["answer"])
    print(f"\nspawned={out['spawned']}  cost=${out['cost_usd']}")
    if out["tree"]:
        print("sub-agents:", [t["role"] for t in out["tree"]])


if __name__ == "__main__":
    _cli()
