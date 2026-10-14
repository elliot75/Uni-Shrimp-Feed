from __future__ import annotations

import logging
from uuid import UUID
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
import psycopg2
from psycopg2.extras import RealDictCursor

from access import get_pond_or_404, require_pond_access, visible_pond_filter
from auth import get_current_user, require_admin
from db import get_db
from models import DeviceActivationCode, DeviceActivationRequest, DeviceCreate, DeviceKeyResponse, DeviceUpdate
from routers.probe_readings import key_hash

router = APIRouter(prefix="/api/devices", tags=["devices"])
logger = logging.getLogger(__name__)


@router.post("/{device_id}/ingest-key", response_model=DeviceKeyResponse)
def issue_ingest_key(device_id: UUID, response: Response, current_user: dict = Depends(require_admin), conn=Depends(get_db)):
    """Create or rotate a device key. Only this response contains the plaintext."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT mac_address FROM shrimp.devices WHERE id = %s FOR UPDATE", (str(device_id),))
        device = cur.fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        if not device["mac_address"]:
            raise HTTPException(status_code=409, detail="Device must have a valid MAC address")
        key = secrets.token_urlsafe(32)
        cur.execute(
            """
            INSERT INTO shrimp.device_api_keys (device_id, key_hash)
            VALUES (%s, %s)
            ON CONFLICT (device_id) DO UPDATE
            SET key_hash = EXCLUDED.key_hash, created_at = now()
            """,
            (str(device_id), key_hash(key)),
        )
        cur.execute("DELETE FROM shrimp.device_activation_codes WHERE device_id = %s", (str(device_id),))
    conn.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"device_id": str(device_id), "device_serial": device["mac_address"], "api_key": key}


@router.post("/{device_id}/activation-code", response_model=DeviceActivationCode)
def issue_activation_code(device_id: UUID, response: Response, current_user: dict = Depends(require_admin), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT mac_address, pond_id, is_active FROM shrimp.devices WHERE id = %s FOR UPDATE",
            (str(device_id),),
        )
        device = cur.fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        if not device["mac_address"] or not device["is_active"] or not device["pond_id"]:
            raise HTTPException(status_code=409, detail="Device must have a valid MAC, be active and bound to a pond")
        code = secrets.token_urlsafe(24)
        cur.execute(
            """
            INSERT INTO shrimp.device_activation_codes (device_id, code_hash, expires_at)
            VALUES (%s, %s, now() + interval '15 minutes')
            ON CONFLICT (device_id) DO UPDATE
            SET code_hash = EXCLUDED.code_hash, expires_at = EXCLUDED.expires_at,
                used_at = NULL, created_at = now()
            RETURNING expires_at
            """,
            (str(device_id), key_hash(code)),
        )
        expires_at = cur.fetchone()["expires_at"]
    conn.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"device_id": str(device_id), "device_serial": device["mac_address"], "activation_code": code, "expires_at": expires_at}


@router.post("/activate", response_model=DeviceKeyResponse)
def activate_device(body: DeviceActivationRequest, response: Response, conn=Depends(get_db)):
    """Exchange an installation code for a device key in one locked transaction."""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Always lock the device before the code, as key/code issuance also does.
            cur.execute(
                "SELECT id, mac_address, pond_id, is_active FROM shrimp.devices WHERE mac_address = %s FOR UPDATE",
                (body.device_serial,),
            )
            device = cur.fetchone()
            if not device:
                raise HTTPException(status_code=401, detail="Invalid or expired activation code")
            cur.execute(
                """
                SELECT used_at, expires_at > clock_timestamp() AS valid
                FROM shrimp.device_activation_codes
                WHERE device_id = %s AND code_hash = %s FOR UPDATE
                """,
                (str(device["id"]), key_hash(body.activation_code)),
            )
            code = cur.fetchone()
            if not code or code["used_at"] is not None or not code["valid"]:
                raise HTTPException(status_code=401, detail="Invalid or expired activation code")
            if not device["is_active"] or not device["pond_id"]:
                raise HTTPException(status_code=409, detail="Device must be active and bound to a pond")
            key = secrets.token_urlsafe(32)
            cur.execute(
                """
                INSERT INTO shrimp.device_api_keys (device_id, key_hash) VALUES (%s, %s)
                ON CONFLICT (device_id) DO UPDATE
                SET key_hash = EXCLUDED.key_hash, created_at = now()
                """,
                (str(device["id"]), key_hash(key)),
            )
            cur.execute(
                "UPDATE shrimp.device_activation_codes SET used_at = clock_timestamp() WHERE device_id = %s",
                (str(device["id"]),),
            )
        conn.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"device_id": device["id"], "device_serial": device["mac_address"], "api_key": key}
    except HTTPException:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=503, detail="Unable to activate device; try again later") from exc


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
        except Exception:
            conn.rollback()
            logger.exception("Device creation failed")
            raise HTTPException(status_code=400, detail="Unable to create device; check the supplied values") from None
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
