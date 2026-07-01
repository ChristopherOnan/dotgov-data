"""
Resilient xAI (Grok) client for AetherCouncil.

Drop this file in next to config.py (or under core/) and import from it
instead of constructing the OpenAI AsyncClient directly. It adds:

  - automatic retry with exponential backoff + jitter on transient failures
    (HTTP 429 / 500 / 502 / 503 / 504 — i.e. the "Service temporarily
    unavailable" 500s you've been hitting)
  - a hard cap on attempts so a real outage fails cleanly instead of hanging
  - graceful degradation: raises a typed XAIUnavailable you can catch
    per-agent so one team member failing doesn't kill the whole run

Usage in core/tech_scout.py (and anywhere else you call xAI):

    from xai_resilient import make_client, chat_with_retry, XAIUnavailable

    client = make_client()
    try:
        resp = await chat_with_retry(
            client,
            model=config.XAI_ANALYSIS_MODEL,   # see config notes
            messages=messages,
            max_tokens=config.XAI_MAX_TOKENS,
        )
    except XAIUnavailable as e:
        log.error("tech_scout: xAI down, skipping this pass: %s", e)
        return {"candidates": [], "error": str(e)}
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any

from openai import (
    AsyncOpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)

log = logging.getLogger("aethercouncil.xai")

XAI_BASE_URL = "https://api.x.ai/v1"

# Transient HTTP statuses worth retrying. 500 = the "Service temporarily
# unavailable" error you're seeing; the rest are the usual transient family.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Tune to taste.
_MAX_ATTEMPTS = 6      # total tries (1 initial + 5 retries)
_BASE_DELAY = 2.0      # seconds; doubles each attempt (2,4,8,16,32)
_MAX_DELAY = 32.0      # cap per-attempt sleep


class XAIUnavailable(RuntimeError):
    """Raised when xAI stays unavailable after all retries."""


def make_client() -> AsyncOpenAI:
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY is not set (add it to .env)")
    return AsyncOpenAI(
        api_key=key,
        base_url=XAI_BASE_URL,
        timeout=120.0,
        max_retries=0,  # we do our own retrying below, with backoff + jitter
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS
    return False


async def chat_with_retry(client: AsyncOpenAI, **kwargs: Any):
    """
    Drop-in replacement for `client.chat.completions.create(**kwargs)` that
    survives transient xAI 500 "Service temporarily unavailable" errors.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below if fatal
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_ATTEMPTS:
                break
            delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
            delay += random.uniform(0, delay * 0.25)  # jitter
            log.warning(
                "xAI call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt, _MAX_ATTEMPTS, exc, delay,
            )
            await asyncio.sleep(delay)

    raise XAIUnavailable(
        f"xAI unavailable after {_MAX_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc
