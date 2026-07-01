# AetherCouncil Security Guidelines

## API Key Rotation

**Rule**: Any OpenRouter key pasted into a chat, log, or transcript is considered exposed and must be rotated immediately. Never store a live key in a tracked file — only in `.env` (git-ignored).

### How to rotate your OpenRouter key:
1. Go to https://openrouter.ai/account/api_keys
2. Click "Delete" on the exposed key
3. Generate a new key
4. Update your `.env` file: `OPENROUTER_API_KEY=sk-or-v1-...new key...`
5. Restart the loop

### Key Management Best Practices

- **Never commit `.env` to git.** Add it to `.gitignore`:
  ```
  .env
  .env.local
  *.key
  ```
- **Use `.env.example`** as a template; commit it without secrets.
- **Rotate keys immediately** if they appear in transcripts, logs, or GitHub.
- **Use different keys** for paper vs live trading (at least use different OpenRouter accounts).
- **Check OpenRouter usage** regularly at https://openrouter.ai/account/usage to spot unauthorized activity.

## Trading Safety

- **Paper mode is default.** Set `PAPER_EXECUTE=1` only for testing with real order mechanics.
- **Live mode requires TWO confirmations:**
  1. `TRADING_MODE=live`
  2. `LIVE_CONFIRM=I_UNDERSTAND_THE_RISK`
- **Calibration gate:** Live trading only allowed after Brier score < 0.24 on paper validation.
- **Daily loss circuit breaker:** Halts new entries if daily loss exceeds -3% equity.
- **Daily token budget:** Hard cap prevents runaway LLM spend (default $2/day → ~$60/month max).

## Data Privacy

- **Finnhub**: Uses IP-based rate limiting; free tier is 60 calls/min.
- **Alpaca**: Paper keys are separate from live keys; use paper credentials only.
- **Logs**: `aethercouncil_loop.log` and `calibration.jsonl` may contain trade data; don't share publicly.

## Running Securely

```bash
# 1. Create .env from template and add YOUR keys
cp .env.example .env
nano .env   # edit in OPENROUTER_API_KEY, ALPACA_* keys

# 2. Verify no secrets are in git
git status --ignored
grep -r "sk-or-v1" .  # should find nothing

# 3. Set restrictive file permissions
chmod 600 .env

# 4. Run in paper mode first
export PAPER_EXECUTE=0
python3 run_loop.py --once

# 5. Only enable execution after validation
export PAPER_EXECUTE=1
python3 run_loop.py --once
```
