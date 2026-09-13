"""Telegram bot: send alerts and bind chat ids via /start CODE."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""


def bot_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def bind_link(code: str) -> str | None:
    if not TELEGRAM_BOT_USERNAME:
        return None
    return f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={code}"


def send_message(chat_id: str, text: str) -> tuple[bool, str | None]:
    if not TELEGRAM_BOT_TOKEN:
        return False, "telegram not configured"
    if not chat_id:
        return False, "missing chat_id"
    try:
        resp = httpx.post(
            f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if resp.status_code >= 400:
            return False, resp.text
        return True, None
    except Exception as exc:
        print(f"[TELEGRAM ERROR] {exc}")
        return False, str(exc)


def get_updates(offset: int | None = None) -> list[dict]:
    if not TELEGRAM_BOT_TOKEN:
        return []
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = httpx.get(f"{API}/getUpdates", params=params, timeout=15)
        data = resp.json()
        return data.get("result") or []
    except Exception as exc:
        print(f"[TELEGRAM POLL ERROR] {exc}")
        return []
