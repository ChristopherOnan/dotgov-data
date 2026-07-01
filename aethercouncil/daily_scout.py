"""
daily_scout.py — the always-on research agent: scan the world every day for new
strategies, models, tools, and catalysts that could make AetherCouncil better.

How it works (multi-agent, cheap):
  1. SCANNER agents (run in parallel, one per focus theme) do a live web/X search
     and return structured candidates. Two backends, auto-selected:
       • NATIVE X  — if XAI_API_KEY is set, uses Grok's native x_search to scan
         all of X/Twitter directly (best coverage). See x_scout.py.
       • WEB       — otherwise uses OpenRouter's web plugin (works today with the
         key you already have). Searches the indexed web incl. X posts.
  2. DEDUP — anything already surfaced on a previous day (by title/url) is dropped,
     so each digest shows only what's NEW.
  3. CURATOR agent (one cheap model) ranks survivors by relevance-to-our-goals
     over effort, and gives each an ADOPT / TEST / WATCH / SKIP verdict.
  4. DIGEST — writes a dated markdown brief to scout_digests/YYYY-MM-DD.md and
     prints a short summary. Cost is tracked and capped.

Run it daily (cron / GCP scheduler), or let run_loop.py fire it once per day.

    python3 daily_scout.py            # run one scan now, write today's digest
    python3 daily_scout.py --themes   # list the focus themes
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger("aethercouncil.scout")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SEEN_PATH = os.getenv("SCOUT_SEEN_PATH", "scout_seen.json")
DIGEST_DIR = os.getenv("SCOUT_DIGEST_DIR", "scout_digests")
SCOUT_BUDGET = float(os.getenv("SCOUT_BUDGET", "0.25"))          # USD hard cap/run
SCANNER_MODEL = os.getenv("SCOUT_SCANNER_MODEL", "openai/gpt-4o-mini")
CURATOR_MODEL = os.getenv("SCOUT_CURATOR_MODEL", "deepseek/deepseek-v4-flash")
MAX_WEB_RESULTS = int(os.getenv("SCOUT_WEB_RESULTS", "4"))

# What we care about. One scanner agent runs per theme. Override via env
# SCOUT_THEMES as a JSON list of {name, query} objects if you want.
DEFAULT_THEMES: list[dict[str, str]] = [
    {"name": "agent-frameworks",
     "query": "newest open-source AI agent frameworks, multi-agent orchestration, "
              "or autonomous-trading agent tooling released or trending this week"},
    {"name": "models",
     "query": "new or newly-cheaper LLMs on OpenRouter or elsewhere this week that "
              "are strong at reasoning/finance for low cost per token"},
    {"name": "market-data",
     "query": "new free or low-cost real-time market data feeds, APIs, or "
              "technical-analysis / order-flow tools announced recently"},
    {"name": "strategies",
     "query": "new quantitative trading strategies, edge ideas, signals, or "
              "risk/calibration methods discussed by credible quants this week"},
    {"name": "catalysts",
     "query": "material news, catalysts, or analyst moves this week on ASTS, RKLB, "
              "ACHR, NVDA, TSLA, PLTR and the space/eVTOL/AI-hardware complex"},
]


def _themes() -> list[dict[str, str]]:
    raw = os.getenv("SCOUT_THEMES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            log.warning("SCOUT_THEMES not valid JSON; using defaults")
    return DEFAULT_THEMES


def _client() -> AsyncOpenAI:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE, timeout=120.0,
                       max_retries=2, default_headers={"X-Title": "AetherCouncil-Scout"})


def _cost(resp: Any) -> float:
    u = getattr(resp, "usage", None)
    if u is None:
        return 0.0
    c = getattr(u, "cost", None)
    if c is None:
        c = (getattr(u, "model_extra", None) or {}).get("cost", 0.0)
    return float(c or 0.0)


def _extract_json_array(text: str) -> list[dict]:
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


_SCANNER_SYS = (
    "You are a research scanner for an autonomous trading-research system called "
    "AetherCouncil (cheap agent swarm + gated Claude/Grok/Gemini council, live "
    "market data, local RSI/MACD/VWAP, ATR risk sizing, calibration). Search the "
    "live web for genuinely NEW, credible, specific items — real releases, papers, "
    "tools, or news, not hype or evergreen explainers. Prefer primary sources."
)

_SCANNER_TMPL = (
    "Find up to 5 NEW items from roughly the last 7 days about:\n{query}\n\n"
    "Return ONLY a JSON array (no prose). Each item:\n"
    '{{"title":"...","summary":"1-2 sentences of what it is","url":"primary source",'
    '"date":"approx YYYY-MM-DD if known else \\"recent\\"",'
    '"why_us":"concretely how it could help AetherCouncil",'
    '"effort":"low|medium|high"}}\n'
    "If nothing genuinely new/credible, return []."
)


async def _scan_theme_web(client: AsyncOpenAI, theme: dict[str, str]) -> list[dict]:
    try:
        resp = await client.chat.completions.create(
            model=SCANNER_MODEL,
            messages=[{"role": "system", "content": _SCANNER_SYS},
                      {"role": "user", "content": _SCANNER_TMPL.format(query=theme["query"])}],
            extra_body={"plugins": [{"id": "web", "max_results": MAX_WEB_RESULTS}]},
            max_tokens=1100,
        )
        cost = _cost(resp)
        items = _extract_json_array(resp.choices[0].message.content or "")
        for it in items:
            it["theme"] = theme["name"]
        log.info("scan[web:%s]: %d items ($%.4f)", theme["name"], len(items), cost)
        return [{"_cost": cost}] + items if items else [{"_cost": cost}]
    except Exception as e:  # noqa: BLE001 - one theme failing shouldn't kill the run
        log.warning("scan[web:%s] failed: %s", theme["name"], e)
        return [{"_cost": 0.0}]


async def _scan_web(themes: list[dict[str, str]]) -> tuple[list[dict], float]:
    client = _client()
    results = await asyncio.gather(*(_scan_theme_web(client, t) for t in themes))
    items, cost = [], 0.0
    for chunk in results:
        for it in chunk:
            if "_cost" in it:
                cost += it["_cost"]
            else:
                items.append(it)
    return items, cost


async def _scan_native() -> tuple[list[dict], float]:
    """Native X scan via Grok x_search (needs XAI_API_KEY). Cost tracked by xAI."""
    from x_scout import scan as xscan
    out = await xscan()
    cands = out.get("candidates", [])
    for c in cands:
        c.setdefault("url", c.get("source_url", ""))
        c.setdefault("why_us", c.get("relevance", ""))
        c["theme"] = c.get("category", "x")
    return cands, 0.0  # xAI bills separately; not on the OpenRouter ledger


# ---- dedup -----------------------------------------------------------------
def _key(item: dict) -> str:
    basis = (item.get("title", "") + "|" + item.get("url", "")).lower().strip()
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _load_seen() -> dict:
    try:
        with open(SEEN_PATH) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_seen(seen: dict) -> None:
    try:
        with open(SEEN_PATH, "w") as f:
            json.dump(seen, f)
    except Exception:  # noqa: BLE001
        pass


# ---- curation --------------------------------------------------------------
_CURATOR_SYS = (
    "You are the research curator for AetherCouncil. Given candidate items found "
    "by scanner agents, judge each for how much it could improve our autonomous "
    "trading-research system relative to the effort to adopt it. Be skeptical; "
    "reject hype. Give each a verdict: ADOPT (clear win, do soon), TEST (promising, "
    "worth a spike), WATCH (keep an eye on), SKIP (not for us)."
)

_CURATOR_TMPL = (
    "Rank these candidates best-first and assign a verdict + one-line rationale.\n"
    "Return ONLY a JSON array, each: "
    '{{"title":"...","verdict":"ADOPT|TEST|WATCH|SKIP","score":0-100,'
    '"rationale":"one line"}}\n\nCANDIDATES:\n{blob}'
)


async def _curate(items: list[dict]) -> tuple[list[dict], float]:
    if not items:
        return [], 0.0
    client = _client()
    blob = "\n".join(
        f"- {it.get('title','?')} [{it.get('theme','?')}] :: {it.get('summary','')} "
        f"(why: {it.get('why_us','')}, effort: {it.get('effort','?')})"
        for it in items
    )
    try:
        resp = await client.chat.completions.create(
            model=CURATOR_MODEL,
            messages=[{"role": "system", "content": _CURATOR_SYS},
                      {"role": "user", "content": _CURATOR_TMPL.format(blob=blob)}],
            max_tokens=1400,
        )
        ranks = _extract_json_array(resp.choices[0].message.content or "")
        # merge verdicts back onto items by title
        by_title = {r.get("title", "").lower(): r for r in ranks}
        for it in items:
            r = by_title.get(it.get("title", "").lower(), {})
            it["verdict"] = r.get("verdict", "WATCH")
            it["score"] = r.get("score", 50)
            it["rationale"] = r.get("rationale", "")
        order = {"ADOPT": 0, "TEST": 1, "WATCH": 2, "SKIP": 3}
        items.sort(key=lambda x: (order.get(x.get("verdict", "WATCH"), 2), -int(x.get("score", 50))))
        return items, _cost(resp)
    except Exception as e:  # noqa: BLE001
        log.warning("curator failed: %s", e)
        return items, 0.0


# ---- digest ----------------------------------------------------------------
_EMOJI = {"ADOPT": "🟢", "TEST": "🔵", "WATCH": "🟡", "SKIP": "⚪"}


def _write_digest(items: list[dict], backend: str, cost: float) -> str:
    os.makedirs(DIGEST_DIR, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DIGEST_DIR, f"{day}.md")
    lines = [f"# AetherCouncil Daily Scout — {day}",
             f"_backend: {backend} · new items: {len(items)} · scan cost: ${cost:.4f}_\n"]
    if not items:
        lines.append("Nothing new cleared the bar today.\n")
    else:
        for it in items:
            v = it.get("verdict", "WATCH")
            lines.append(f"### {_EMOJI.get(v,'🟡')} {v} · {it.get('title','?')}  "
                         f"`{it.get('theme','?')}`")
            lines.append(f"- {it.get('summary','')}")
            if it.get("why_us"):
                lines.append(f"- **Why us:** {it['why_us']}")
            if it.get("rationale"):
                lines.append(f"- **Curator:** {it['rationale']} (score {it.get('score','?')}, "
                             f"effort {it.get('effort','?')})")
            if it.get("url"):
                lines.append(f"- Source: {it['url']}")
            lines.append("")
    text = "\n".join(lines)
    with open(path, "w") as f:
        f.write(text)
    return path


def _console_summary(items: list[dict], backend: str, cost: float, path: str) -> str:
    top = [it for it in items if it.get("verdict") in ("ADOPT", "TEST")][:8]
    out = [f"\n=== DAILY SCOUT ({backend}) — {len(items)} new, ${cost:.4f} ===",
           f"digest: {path}"]
    if not top:
        out.append("No ADOPT/TEST items today (see digest for WATCH list).")
    for it in top:
        out.append(f"  {_EMOJI.get(it.get('verdict'),'🟡')} {it.get('verdict'):5} "
                   f"{it.get('title','?')[:70]}")
    return "\n".join(out)


async def run_daily_scout() -> dict:
    themes = _themes()
    use_native = bool(os.getenv("XAI_API_KEY"))
    backend = "native-x" if use_native else "web"
    log.info("daily scout start (backend=%s, %d themes)", backend, len(themes))

    items, scan_cost = await (_scan_native() if use_native else _scan_web(themes))

    # dedup against what we've already surfaced
    seen = _load_seen()
    fresh = []
    for it in items:
        k = _key(it)
        if k in seen:
            continue
        seen[k] = {"title": it.get("title"), "first_seen": datetime.now(timezone.utc).isoformat()}
        fresh.append(it)
    log.info("dedup: %d/%d are new", len(fresh), len(items))

    curated, curate_cost = await _curate(fresh)
    total = round(scan_cost + curate_cost, 6)
    if total > SCOUT_BUDGET:
        log.warning("scout cost $%.4f exceeded soft budget $%.2f", total, SCOUT_BUDGET)

    path = _write_digest(curated, backend, total)
    _save_seen(seen)
    summary = _console_summary(curated, backend, total, path)
    return {"backend": backend, "new": len(curated), "cost_usd": total,
            "digest": path, "summary": summary, "items": curated}


def _cli() -> None:
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if "--themes" in sys.argv:
        for t in _themes():
            print(f"  {t['name']:18} {t['query']}")
        return
    out = asyncio.run(run_daily_scout())
    print(out["summary"])


if __name__ == "__main__":
    _cli()
