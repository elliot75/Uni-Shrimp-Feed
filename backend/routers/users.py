from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from access import farmer_ids_for_salesperson
from auth import get_current_user, hash_password, require_admin
from db import get_db
from models import AssignmentBody, UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _public(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("created_by"):
        d["created_by"] = str(d["created_by"])
    d.pop("password_hash", None)
    d.pop("telegram_bind_code", None)
    d["telegram_bound"] = bool(d.pop("telegram_chat_id", None))
    return d


@router.get("")
def list_users(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if current_user["role"] == "admin":
        sql = """
            SELECT id, username, email, role, display_name, locale, phone,
                   telegram_chat_id, is_active, created_at
            FROM shrimp.users ORDER BY created_at
        """
        args = []
    elif current_user["role"] == "salesperson":
        sql = """
            SELECT id, username, email, role, display_name, locale, phone,
                   telegram_chat_id, is_active, created_at
            FROM shrimp.users
            WHERE id = %s OR id IN (
                SELECT farmer_id FROM shrimp.salesperson_farmers WHERE salesperson_id = %s
            )
            ORDER BY created_at
        """
        args = [current_user["id"], current_user["id"]]
    else:
        sql = """
            SELECT id, username, email, role, display_name, locale, phone,
                   telegram_chat_id, is_active, created_at
            FROM shrimp.users WHERE id = %s
        """
        args = [current_user["id"]]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return [_public(r) for r in rows]


@router.post("")
def create_user(body: UserCreate, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute(
                """
                INSERT INTO shrimp.users (
                    username, email, password_hash, role, display_name, locale, phone, is_active, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    body.username,
                    body.email,
                    hash_password(body.password),
                    body.role,
                    body.display_name,
                    body.locale,
                    body.phone,
                    body.is_active,
                    admin["id"],
                ),
            )
            row = cur.fetchone()
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=f"Could not create user: {exc}")
    return _public(row)


@router.patch("/{user_id}")
def update_user(user_id: UUID, body: UserUpdate, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields")
    if "password" in fields:
        fields["password_hash"] = hash_password(fields.pop("password"))
    sets = [f"{k} = %s" for k in fields]
    args = list(fields.values()) + [str(user_id)]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE shrimp.users SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    conn.commit()
    return _public(row)


@router.get("/assignments")
def list_assignments(admin: dict = Depends(require_admin), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT sf.salesperson_id, sf.farmer_id, sf.created_at,
                   s.username AS salesperson_username, s.display_name AS salesperson_name,
                   f.username AS farmer_username, f.display_name AS farmer_name
            FROM shrimp.salesperson_farmers sf
            JOIN shrimp.users s ON s.id = sf.salesperson_id
            JOIN shrimp.users f ON f.id = sf.farmer_id
            ORDER BY sf.created_at
            """
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["salesperson_id"] = str(d["salesperson_id"])
        d["farmer_id"] = str(d["farmer_id"])
        out.append(d)
    return out


@router.post("/assignments")
def create_assignment(body: AssignmentBody, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, role FROM shrimp.users WHERE id IN (%s, %s)", (str(body.salesperson_id), str(body.farmer_id)))
        roles = {str(r["id"]): r["role"] for r in cur.fetchall()}
        if roles.get(str(body.salesperson_id)) != "salesperson":
            raise HTTPException(status_code=400, detail="salesperson_id must be a salesperson")
        if roles.get(str(body.farmer_id)) != "farmer":
            raise HTTPException(status_code=400, detail="farmer_id must be a farmer")
        try:
            cur.execute(
                """
                INSERT INTO shrimp.salesperson_farmers (salesperson_id, farmer_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (str(body.salesperson_id), str(body.farmer_id)),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.delete("/assignments/{salesperson_id}/{farmer_id}")
def delete_assignment(salesperson_id: UUID, farmer_id: UUID, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM shrimp.salesperson_farmers WHERE salesperson_id = %s AND farmer_id = %s",
            (str(salesperson_id), str(farmer_id)),
        )
    conn.commit()
    return {"ok": True}
