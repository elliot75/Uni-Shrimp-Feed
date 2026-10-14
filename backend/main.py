"""Uni-Shrimp FastAPI app."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from alerts import evaluate_stale_devices, flush_notifications, process_pending_readings, retry_unnotified
from db import get_connection
from routers import alerts as alerts_routes
from routers import auth_routes, dashboard, devices, ponds, probe_readings, users
from telegram_service import get_updates

_tg_offset = None


def _handle_telegram_updates() -> None:
    global _tg_offset
    updates = get_updates(_tg_offset)
    if not updates:
        return
    conn = get_connection()
    acked = _tg_offset
    try:
        for upd in updates:
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            if text.startswith("/start") and chat_id:
                parts = text.split(maxsplit=1)
                code = parts[1] if len(parts) > 1 else ""
                if code:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE shrimp.users
                            SET telegram_chat_id = %s,
                                telegram_bind_code = NULL,
                                telegram_bind_expires_at = NULL,
                                updated_at = now()
                            WHERE id = (
                                SELECT id FROM shrimp.users
                                WHERE telegram_bind_code = %s
                                  AND telegram_bind_expires_at > now()
                                LIMIT 1
                            )
                            RETURNING id
                            """,
                            (chat_id, code),
                        )
                        row = cur.fetchone()
                    from telegram_service import send_message
                    if row:
                        send_message(chat_id, "Uni-Shrimp: Telegram bound / Đã liên kết / 已綁定")
                    else:
                        send_message(chat_id, "Uni-Shrimp: invalid or expired code")
            conn.commit()
            acked = upd["update_id"] + 1
    except Exception:
        conn.rollback()
        raise
    finally:
        _tg_offset = acked
        conn.close()


def _worker_tick() -> None:
    conn = get_connection()
    try:
        process_pending_readings(conn)
        evaluate_stale_devices(conn)
        conn.commit()
        flush_notifications(conn)
        retry_unnotified(conn)
    finally:
        conn.close()
    _handle_telegram_updates()


async def _worker() -> None:
    while True:
        try:
            await asyncio.to_thread(_worker_tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[WORKER] {exc}")
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SKIP_WORKER") == "1":
        yield
        return
    task = asyncio.create_task(_worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Uni-Shrimp", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_routes.router)
app.include_router(users.router)
app.include_router(ponds.router)
app.include_router(devices.router)
app.include_router(alerts_routes.router)
app.include_router(dashboard.router)
app.include_router(probe_readings.router)


@app.get("/api/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}
