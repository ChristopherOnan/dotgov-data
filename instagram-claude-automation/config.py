"""
Configuration loader for Instagram Claude Automation.

Loads secrets and settings from environment variables / .env file.
Never hardcode credentials — use a .env file (see .env.example).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


def _require(var: str) -> str:
    """Return an env var or raise with a helpful message."""
    val = os.getenv(var)
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {var}. "
            f"Copy .env.example to .env and fill in your credentials."
        )
    return val


# --- Required ---
IG_USER_ID: str = _require("IG_USER_ID")
ACCESS_TOKEN: str = _require("ACCESS_TOKEN")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

# --- Optional ---
FB_APP_ID: str = os.getenv("FB_APP_ID", "")
FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "")
IG_API_VERSION: str = os.getenv("IG_API_VERSION", "v22.0")
MOCK_MODE: bool = os.getenv("MOCK_MODE", "false").lower() == "true"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Derived ---
BASE_URL: str = f"https://graph.facebook.com/{IG_API_VERSION}"

# --- Constants ---
MAX_CAPTION_LENGTH = 2200
MAX_HASHTAGS = 30  # IG limit
PUBLISHING_LIMIT_PER_24H = 100  # approximate IG rate limit
STATUS_POLL_INTERVAL = 5  # seconds between status checks
STATUS_POLL_MAX_ATTEMPTS = 60  # max polls (~5 min)
