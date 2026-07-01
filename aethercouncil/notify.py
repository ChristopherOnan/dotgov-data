"""
notify.py — push AetherCouncil alerts to your phone (or wherever you watch).

Zero required deps: uses urllib for Telegram and stdlib smtplib for email.
Auto-selects a channel from whatever env vars are present; falls back to
stdout/log so nothing ever crashes for lack of config.

Channels (checked in order):
  • Telegram : TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID   (easiest for phone push)
  • Email    : SMTP_HOST, SMTP_USER, SMTP_PASS, NOTIFY_EMAIL [, SMTP_PORT]
  • Console  : always works (prints + logs)

You can force/disable channels with NOTIFY_CHANNEL = telegram | email | console.

    from notify import notify
    notify("Daily board", "🟢 RKLB ... 🔴 MSTR ...")
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

log = logging.getLogger("aethercouncil.notify")


def _telegram_ready() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def _email_ready() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER")
                and os.getenv("SMTP_PASS") and os.getenv("NOTIFY_EMAIL"))


def _send_telegram(title: str, body: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    text = f"*{title}*\n{body}" if title else body
    # Telegram hard-caps messages at 4096 chars.
    text = text[:4000]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.loads(r.read()).get("ok", False)
        if not ok:
            log.warning("telegram send returned ok=false")
        return bool(ok)
    except Exception as e:  # noqa: BLE001
        log.warning("telegram send failed: %s", e)
        return False


def _send_email(title: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pw = os.getenv("SMTP_PASS")
    to = os.getenv("NOTIFY_EMAIL")
    msg = MIMEText(body)
    msg["Subject"] = f"[AetherCouncil] {title}"
    msg["From"] = user
    msg["To"] = to
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("email send failed: %s", e)
        return False


def notify(title: str, body: str) -> str:
    """Send an alert on the best available channel. Returns the channel used."""
    forced = (os.getenv("NOTIFY_CHANNEL") or "").lower()

    if forced == "console":
        pass  # skip remote channels
    elif forced == "telegram" or (not forced and _telegram_ready()):
        if _telegram_ready() and _send_telegram(title, body):
            return "telegram"
    elif forced == "email" or (not forced and _email_ready()):
        if _email_ready() and _send_email(title, body):
            return "email"

    # Fallback: never fail silently — surface it locally.
    print(f"\n[NOTIFY] {title}\n{body}\n")
    log.info("notify (console): %s", title)
    return "console"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ch = notify("Test alert",
                "If you see this on your phone, notifications work. 🟢")
    print(f"sent via: {ch}")
