from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from auth import (
    bump_token_version,
    create_access_token,
    get_current_user,
    hash_password,
    user_token_version,
    verify_password,
)
from db import get_db
from models import LoginRequest, MeUpdate, PasswordChange
from telegram_service import bind_link, bot_configured

router = APIRouter(prefix="/api/auth", tags=["auth"])
_LOGIN_WINDOW = timedelta(minutes=15)
_LOGIN_LIMIT = 8
_login_failures: dict[str, list[datetime]] = {}


def _session_public(user: dict) -> dict:
    return {
        "id": str(user["id"]) if user.get("id") is not None else None,
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role"),
        "display_name": user.get("display_name"),
        "locale": user.get("locale"),
        "phone": user.get("phone"),
        "is_active": user.get("is_active", True),
        "telegram_bound": bool(user.get("telegram_chat_id")),
    }


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


def _prune_failures(username: str) -> list[datetime]:
    now = datetime.now(timezone.utc)
    recent = [stamp for stamp in _login_failures.get(username, []) if now - stamp < _LOGIN_WINDOW]
    if recent:
        _login_failures[username] = recent
    else:
        _login_failures.pop(username, None)
    return recent


@router.post("/login")
def login(body: LoginRequest, conn=Depends(get_db)):
    username = body.username.lower()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.users WHERE lower(username) = lower(%s)
            """,
            (body.username,),
        )
        user = cur.fetchone()
    if user and verify_password(body.password, user["password_hash"]):
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account disabled")
        _login_failures.pop(username, None)
        token = create_access_token({
            "sub": str(user["id"]),
            "role": user["role"],
            "username": user["username"],
            "ver": user_token_version(conn, user["id"]),
        })
        return {"access_token": token, "token_type": "bearer", "user": _public_user(user)}
    if len(_prune_failures(username)) >= _LOGIN_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts")
    _login_failures.setdefault(username, []).append(datetime.now(timezone.utc))
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return _session_public(current_user)


@router.patch("/me")
def update_me(body: MeUpdate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return _session_public(current_user)
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


@router.post("/me/password")
def change_password(
    body: PasswordChange,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT password_hash FROM shrimp.users WHERE id = %s", (current_user["id"],))
        row = cur.fetchone()
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="current_password_incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="password_unchanged")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE shrimp.users
            SET password_hash = %s, updated_at = now()
            WHERE id = %s
            """,
            (hash_password(body.new_password), current_user["id"]),
        )
    bump_token_version(conn, current_user["id"])
    conn.commit()
    return {"ok": True}


@router.post("/telegram/bind")
def start_telegram_bind(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not bot_configured():
        raise HTTPException(status_code=400, detail="Telegram bot is not configured")
    code = secrets.token_urlsafe(16)
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
