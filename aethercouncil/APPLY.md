# AetherCouncil fix — apply steps

This fixes the two real problems from your `grok` session:
1. xAI `500 Service temporarily unavailable` crashing runs.
2. The council giving shallow, "fast" answers.

I can't reach your Mac, so run these yourself. ~5 minutes.

---

## Step 0 — unblock `grok` itself (do this first, only you can)

The Composer 2.5 turns are failing because **xAI is 500-ing AND your context
is at 152K/200K with ~6-min turns** (huge requests die first under load).

    # in the grok CLI:
    /clear            # or quit and relaunch `grok`

Start a FRESH, small session. No code below helps until grok can reach the
model again — and clearing context is the single biggest lever.

---

## Step 1 — add the resilient client

Copy `xai_resilient.py` into your project (next to `config.py`):

    cp xai_resilient.py /Users/mac/AetherCouncil/

## Step 2 — use it in tech_scout (and any other xAI caller)

In `core/tech_scout.py`, replace the raw client construction + call:

    # OLD
    client = _client()
    resp = await client.chat.completions.create(model=..., messages=...)

    # NEW
    from xai_resilient import make_client, chat_with_retry, XAIUnavailable
    client = make_client()
    try:
        resp = await chat_with_retry(
            client,
            model=config.XAI_ANALYSIS_MODEL,
            messages=messages,
            max_tokens=config.XAI_MAX_TOKENS,
        )
    except XAIUnavailable as e:
        log.error("tech_scout: xAI unavailable, skipping pass: %s", e)
        return {"candidates": [], "error": str(e)}

## Step 3 — make answers DEEP, not fast (config.py)

Add these (env-overridable). Set XAI_ANALYSIS_MODEL to the strongest
reasoning model your xAI account has access to — NOT a "fast" variant.

    import os
    XAI_ANALYSIS_MODEL = os.getenv("XAI_ANALYSIS_MODEL", "<your-strongest-grok-reasoning-model>")
    XAI_FAST_MODEL     = os.getenv("XAI_FAST_MODEL", "<a-fast-grok-model>")
    XAI_MAX_TOKENS     = int(os.getenv("XAI_MAX_TOKENS", "8000"))

Then in your agent/council prompt construction, require depth. Example
system-prompt stiffening:

    "You are a research analyst on the Aether Council. Do NOT answer quickly.
     Work in passes: (1) gather evidence with sources, (2) critique your own
     reasoning and list what would change your mind, (3) give a final call
     with an explicit probability and the reasoning that justifies it.
     Never give a one-line answer; show the work."

## Step 4 — verify

    cd /Users/mac/AetherCouncil
    python3 -c "import xai_resilient; print('import ok')"
    python3 -c "
    import asyncio, config
    from core.tech_scout import run_team
    r = asyncio.run(run_team(force=True))
    print('candidates', len(r.get('candidates', [])))
    "

If xAI is mid-outage you'll now get a clean 'xAI unavailable after 6
attempts' instead of a crash — that's the graceful-degradation path working.

---

## Notes
- Model names in Step 3 are placeholders on purpose — set them to the exact
  models your xAI key can use (run your account's model list to confirm).
- xAI base URL is hardcoded to https://api.x.ai/v1 in xai_resilient.py;
  change it there if your account uses a different endpoint.
