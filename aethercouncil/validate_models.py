"""
validate_models.py — fail loudly on bad model names at startup.

Checks every model slug the agent pool is configured to use (the cheap SWARM
plus the gated expert COUNCIL) against OpenRouter's live model list, and refuses
to start (or warns) if any slug is unknown. This catches hallucinated model
names (e.g. "grok-4.20-multi-agent-0309") before they silently fail every call.

Call validate_models() once at app startup, or run this file directly:

    python3 validate_models.py
"""

from __future__ import annotations

import asyncio
import logging

from agent_pool import SWARM, COUNCIL, make_client

log = logging.getLogger("aethercouncil.models")


class InvalidModelConfig(RuntimeError):
    pass


async def list_available_models() -> list[str]:
    client = make_client()
    raw = await client.models.list()
    data = getattr(raw, "data", raw)
    return sorted(getattr(m, "id", str(m)) for m in data)


async def validate_models(strict: bool = True) -> dict[str, bool]:
    """
    Returns {model_slug: ok}. If strict and any configured model is unknown,
    raises InvalidModelConfig listing the bad slugs.
    """
    available = set(await list_available_models())
    log.info("OpenRouter exposes %d models", len(available))

    results: dict[str, bool] = {}
    bad: list[str] = []
    for spec in [*SWARM, *COUNCIL]:
        ok = spec.model in available
        results[spec.model] = ok
        if ok:
            log.info("OK  [%-7s] %s", spec.tier, spec.model)
        else:
            bad.append(f"{spec.role}={spec.model!r}")
            log.error("BAD [%-7s] %s (%s) — not in OpenRouter's list",
                      spec.tier, spec.model, spec.role)

    if bad and strict:
        # Suggest close matches to help fix typos fast.
        hint = ""
        for spec in [*SWARM, *COUNCIL]:
            if spec.model not in available:
                stem = spec.model.split("/")[-1].split("-")[0].lower()
                near = [m for m in sorted(available) if stem in m.lower()][:5]
                if near:
                    hint += f"\n  for {spec.model!r} try: {', '.join(near)}"
        raise InvalidModelConfig(
            "Invalid model slug(s): " + "; ".join(bad) + "." + (hint or "")
        )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        asyncio.run(validate_models(strict=True))
        print("\nAll configured models are valid.")
    except InvalidModelConfig as e:
        print("\nFAILED:", e)
        raise SystemExit(1)
