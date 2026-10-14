"""JWT auth and password hashing."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from psycopg2.extras import RealDictCursor

from db import get_db

JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET.strip() or JWT_SECRET == "fallback-secret":
    raise RuntimeError("JWT_SECRET must be configured with a private signing key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
_token_version_ready = None


def token_version_ready(conn) -> bool:
    global _token_version_ready
    if _token_version_ready:
        return True
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'shrimp' AND table_name = 'users' AND column_name = 'token_version'
            """
        )
        _token_version_ready = cur.fetchone() is not None
    return _token_version_ready


def user_token_version(conn, user_id) -> int:
    if not token_version_ready(conn):
        return 1
    with conn.cursor() as cur:
        cur.execute("SELECT token_version FROM shrimp.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return int((row or {}).get("token_version") or 1)


def bump_token_version(conn, user_id) -> None:
    if not token_version_ready(conn):
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shrimp.users SET token_version = token_version + 1 WHERE id = %s",
            (user_id,),
        )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    conn=Depends(get_db),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    try:
        user_id = str(UUID(user_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, username, email, role, display_name, locale, phone,
                   telegram_chat_id, is_active
            FROM shrimp.users WHERE id = %s
            """,
            (user_id,),
        )
        user = cur.fetchone()
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Inactive or missing user")
    claimed = payload.get("ver", 1)
    try:
        claimed = int(claimed)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    if user_token_version(conn, user["id"]) != claimed:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user["id"] = str(user["id"])
    return dict(user)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_staff(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("admin", "salesperson"):
        raise HTTPException(status_code=403, detail="Staff access required")
    return current_user
