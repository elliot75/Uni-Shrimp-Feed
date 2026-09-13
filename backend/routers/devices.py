from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from access import get_pond_or_404, require_pond_access, visible_pond_filter
from auth import get_current_user
from db import get_db
from models import DeviceCreate, DeviceUpdate

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _clean(row) -> dict:
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat") and not isinstance(v, str):
            d[k] = v.isoformat()
    return d


def _can_manage_devices(user: dict) -> bool:
    return user["role"] in ("admin", "salesperson")


@router.get("")
def list_devices(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if current_user["role"] == "admin":
        sql = """
            SELECT d.*, p.code AS pond_code, p.name AS pond_name, p.farmer_id
            FROM shrimp.devices d
            LEFT JOIN shrimp.ponds p ON p.id = d.pond_id
            ORDER BY d.serial
        """
        args = []
    else:
        where, args = visible_pond_filter(current_user, conn)
        sql = f"""
            SELECT d.*, p.code AS pond_code, p.name AS pond_name, p.farmer_id
            FROM shrimp.devices d
            JOIN shrimp.ponds p ON p.id = d.pond_id
            WHERE {where}
            ORDER BY d.serial
        """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return [_clean(r) for r in rows]


@router.post("")
def create_device(body: DeviceCreate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not _can_manage_devices(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    if body.pond_id:
        pond = get_pond_or_404(conn, str(body.pond_id))
        require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute(
                """
                INSERT INTO shrimp.devices (serial, pond_id, name, notes)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (body.serial, str(body.pond_id) if body.pond_id else None, body.name, body.notes),
            )
            row = cur.fetchone()
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    return _clean(row)


@router.patch("/{device_id}")
def update_device(device_id: UUID, body: DeviceUpdate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not _can_manage_devices(current_user) and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM shrimp.devices WHERE id = %s", (str(device_id),))
        device = cur.fetchone()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device["pond_id"]:
        pond = get_pond_or_404(conn, device["pond_id"])
        require_pond_access(current_user, pond, conn)
    elif current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can bind unassigned devices")
    fields = body.model_dump(exclude_unset=True)
    if fields.pop("unbind", False):
        fields["pond_id"] = None
    if fields.get("pond_id"):
        pond = get_pond_or_404(conn, str(fields["pond_id"]))
        require_pond_access(current_user, pond, conn)
        fields["pond_id"] = str(fields["pond_id"])
    if not fields:
        return _clean(device)
    sets = [f"{k} = %s" for k in fields]
    args = list(fields.values()) + [str(device_id)]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE shrimp.devices SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    conn.commit()
    return _clean(row)
