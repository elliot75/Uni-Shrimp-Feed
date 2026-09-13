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
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


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
