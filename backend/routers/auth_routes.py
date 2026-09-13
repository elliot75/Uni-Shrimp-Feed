from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from db import get_db
from models import LoginRequest, MeUpdate
from telegram_service import bind_link, bot_configured

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public_user(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "display_name": row["display_name"],
        "locale": row["locale"],
        "phone": row.get("phone"),
        "telegram_bound": bool(row.get("telegram_chat_id")),
        "is_active": row.get("is_active", True),
    }


@router.post("/login")
def login(body: LoginRequest, conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.users WHERE lower(username) = lower(%s)
            """,
            (body.username,),
        )
        user = cur.fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token({"sub": str(user["id"]), "role": user["role"], "username": user["username"]})
    return {"access_token": token, "token_type": "bearer", "user": _public_user(user)}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user | {"telegram_bound": bool(current_user.get("telegram_chat_id"))}


@router.patch("/me")
def update_me(body: MeUpdate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return current_user
    sets = []
    args = []
    for key, val in fields.items():
        sets.append(f"{key} = %s")
        args.append(val)
    sets.append("updated_at = now()")
    args.append(current_user["id"])
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE shrimp.users SET {', '.join(sets)} WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    conn.commit()
    return _public_user(row)


@router.post("/telegram/bind")
def start_telegram_bind(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not bot_configured():
        raise HTTPException(status_code=400, detail="Telegram bot is not configured")
    code = secrets.randbelow(900000) + 100000
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE shrimp.users
            SET telegram_bind_code = %s, telegram_bind_expires_at = %s, updated_at = now()
            WHERE id = %s
            """,
            (str(code), expires, current_user["id"]),
        )
    conn.commit()
    return {"code": str(code), "link": bind_link(str(code)), "expires_at": expires.isoformat()}
