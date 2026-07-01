"""
x_scout.py — native X/Twitter + web discovery for AetherCouncil.

First-principles design: instead of scraping X or using a fragile unofficial
API, this uses xAI's *native* `x_search` and `web_search` tools through the
Grok Responses API. Grok does the live scan of X itself and returns
structured discovery candidates — new technologies, tools, strategies, or
upgrades that could make AetherCouncil more robust and cutting-edge.

Depends on xai_resilient.py (make_client) which you already have.

Run it standalone to test:
    python3 -m x_scout
or:
    python3 x_scout.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from xai_resilient import make_client, XAIUnavailable

log = logging.getLogger("aethercouncil.x_scout")

# ---- knobs (override via environment variables) ----------------------------

# Real, valid xAI model. NOT "grok-4.20-multi-agent-0309" (that was invented).
SCOUT_MODEL = os.getenv("XAI_SCOUT_MODEL", "grok-4.3")

# How many days back to scan.
SCOUT_LOOKBACK_DAYS = int(os.getenv("SCOUT_LOOKBACK_DAYS", "7"))

# FinTwit / tech accounts worth weighting (comma-separated). Empty = all of X.
SCOUT_X_HANDLES: list[str] = [
    h.strip() for h in os.getenv("SCOUT_X_HANDLES", "").split(",") if h.strip()
]

# Tickers / themes you care about, used to focus the scan.
SCOUT_FOCUS = os.getenv(
    "SCOUT_FOCUS",
    "ASTS, RKLB, ACHR and the space / launch / eVTOL complex; plus tooling that "
    "improves an autonomous multi-agent trading-research system (live data, "
    "sentiment, orchestration, risk, calibration).",
)

_SYSTEM = (
    "You are the Tech Scout for the Aether Council, an autonomous multi-agent "
    "trading-research system (Grok + Claude + Gemini). Think from first "
    "principles. Your job is to scan X and the web for genuinely NEW and useful "
    "things we could adopt: new models/APIs/tools, data sources, agent "
    "orchestration techniques, risk/calibration methods, or market strategies. "
    "Prefer signal over hype. Reject vague threads and influencer noise. "
    "For each candidate, judge concretely how it would make OUR system more "
    "robust or cutting-edge."
)

_USER_TMPL = (
    "Scan X (and the web where useful) from {start} to {end} for new "
    "technologies, tools, strategies, or upgrades relevant to:\n{focus}\n\n"
    "Return ONLY a JSON array (no prose) of up to 8 candidates, each:\n"
    "{{\n"
    '  "title": "...",\n'
    '  "summary": "what it is, in one or two sentences",\n'
    '  "category": "model|data|tooling|orchestration|risk|strategy",\n'
    '  "source_url": "primary X post or link",\n'
    '  "relevance": "how it concretely helps the Aether Council",\n'
    '  "effort": "low|medium|high",\n'
    '  "suggested_action": "the specific thing we should build or test"\n'
    "}}\n"
    "Rank by (relevance / effort). If nothing meets the bar, return []."
)


def _tools() -> list[dict[str, Any]]:
    x_tool: dict[str, Any] = {
        "type": "x_search",
        "from_date": (
            datetime.now(timezone.utc) - timedelta(days=SCOUT_LOOKBACK_DAYS)
        ).date().isoformat(),
        "to_date": datetime.now(timezone.utc).date().isoformat(),
        "enable_image_understanding": True,
    }
    if SCOUT_X_HANDLES:
        x_tool["allowed_x_handles"] = SCOUT_X_HANDLES[:20]
    return [x_tool, {"type": "web_search"}]


def _extract_json(text: str) -> list[dict[str, Any]]:
    """Tolerant: pull the first JSON array out of the model's reply."""
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        log.warning("x_scout: could not parse JSON from model reply")
        return []


async def scan() -> dict[str, Any]:
    """
    Run a live X/web scan. Returns:
      {"candidates": [...], "model": str}  on success
      {"candidates": [], "error": str}     on graceful failure
    """
    client = make_client()
    now = datetime.now(timezone.utc)
    user = _USER_TMPL.format(
        start=(now - timedelta(days=SCOUT_LOOKBACK_DAYS)).date().isoformat(),
        end=now.date().isoformat(),
        focus=SCOUT_FOCUS,
    )

    # Reuse the resilient retry path. If your tech_scout already defines
    # responses_with_retry(), import and use that instead of this inline guard.
    try:
        resp = await client.responses.create(
            model=SCOUT_MODEL,
            input=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            tools=_tools(),
        )
    except XAIUnavailable as e:
        log.error("x_scout: xAI unavailable: %s", e)
        return {"candidates": [], "error": str(e)}
    except Exception as e:  # noqa: BLE001
        log.error("x_scout: unexpected failure: %s", e, exc_info=True)
        return {"candidates": [], "error": repr(e)}

    text = getattr(resp, "output_text", None) or str(resp)
    candidates = _extract_json(text)
    log.info("x_scout: %d candidates", len(candidates))
    return {"candidates": candidates, "model": SCOUT_MODEL}


def _print_report(result: dict[str, Any]) -> None:
    cands = result.get("candidates", [])
    if not cands:
        print("No candidates.", result.get("error", ""))
        return
    print(f"\n=== X/WEB SCOUT — {len(cands)} candidates ({result.get('model')}) ===\n")
    for i, c in enumerate(cands, 1):
        print(f"[{i}] {c.get('title','?')}  ({c.get('category','?')}, "
              f"effort={c.get('effort','?')})")
        print(f"    {c.get('summary','')}")
        print(f"    why: {c.get('relevance','')}")
        print(f"    do : {c.get('suggested_action','')}")
        print(f"    src: {c.get('source_url','')}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _print_report(asyncio.run(scan()))
