"""
params.py — the single source of truth for tunable strategy parameters.

Resolution order for every parameter:  tuned (params.json)  ->  env var  ->  default.

The tuner (tuner.py) writes params.json only when a new setting beats the current
one OUT OF SAMPLE, so live modules read whatever has been validated without any
code change. Keeping this tiny and dependency-free means every consumer
(stream_indicators, trading_engine, portfolio) can import it cheaply.

    from params import P
    ta = LiveTA(oversold=P("oversold", 30.0), overbought=P("overbought", 70.0))
"""

from __future__ import annotations

import json
import os

PARAMS_PATH = os.getenv("PARAMS_PATH", "params.json")

# name -> (env var, default). The tuner only searches over these.
_SPEC = {
    "oversold":   ("RSI_OVERSOLD", 30.0),
    "overbought": ("RSI_OVERBOUGHT", 70.0),
    "stop_mult":  ("STOP_ATR_MULT", 1.5),
    "max_hold":   ("MAX_HOLD_DAYS", 5),
    "target_r":   ("TARGET_R", 2.0),
}

_cache: dict | None = None


def _tuned() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(PARAMS_PATH) as f:
                _cache = json.load(f).get("params", {})
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def reload() -> None:
    """Drop the cache so a fresh tune is picked up without a restart."""
    global _cache
    _cache = None


def P(name: str, default=None):
    """Resolve a tunable parameter: tuned -> env -> spec default -> arg default."""
    env_name, spec_default = _SPEC.get(name, (None, default))
    tuned = _tuned().get(name)
    if tuned is not None:
        return tuned
    if env_name and os.getenv(env_name) is not None:
        raw = os.getenv(env_name)
        try:
            return type(spec_default)(raw)
        except (TypeError, ValueError):
            return raw
    return spec_default if spec_default is not None else default


def save(params: dict, meta: dict | None = None) -> None:
    """Persist a validated parameter set (called by the tuner)."""
    payload = {"params": params}
    if meta:
        payload["meta"] = meta
    with open(PARAMS_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    reload()


def current() -> dict:
    """Everything the system is currently using (tuned or default)."""
    return {k: P(k) for k in _SPEC}


if __name__ == "__main__":
    print("active params:", json.dumps(current(), indent=2))
