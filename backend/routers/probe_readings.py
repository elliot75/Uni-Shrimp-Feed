"""HTTP ingestion for ESP32 devices, using the existing database ingest contract."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader
from psycopg2.extras import Json, RealDictCursor

from db import get_db
from models import ProbeReadingCreate, ProbeReadingReceipt

router = APIRouter(prefix="/api/probe-readings", tags=["probe-readings"])
device_key_header = APIKeyHeader(name="X-Device-Key", auto_error=False)
logger = logging.getLogger(__name__)
MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def require_device_key(key: str | None = Depends(device_key_header)) -> str:
    if not key:
        raise HTTPException(status_code=401, detail="Device key required")
    return key_hash(key)


@router.post("", response_model=ProbeReadingReceipt)
def ingest_reading(
    body: ProbeReadingCreate,
    hashed_key: str = Depends(require_device_key),
    conn=Depends(get_db),
):
    if body.recorded_at > datetime.now(timezone.utc) + MAX_FUTURE_CLOCK_SKEW:
        raise HTTPException(status_code=422, detail="recorded_at is too far in the future; check the device clock")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT d.id FROM shrimp.devices d
                JOIN shrimp.device_api_keys k ON k.device_id = d.id
                WHERE k.key_hash = %s AND d.mac_address = %s AND d.is_active = true
                """,
                (hashed_key, body.device_serial),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=401, detail="Invalid device credentials")
            cur.execute(
                """
                SELECT shrimp.ingest_probe_reading(
                    p_device_serial := %s, p_recorded_at := %s,
                    p_ph := %s, p_ph_mv := %s, p_ph_temp_c := %s,
                    p_conductivity_us_cm := %s, p_salinity_ppt := %s,
                    p_cond_temp_c := %s, p_tds_mg_l := %s,
                    p_do_mg_l := %s, p_do_sat_pct := %s, p_do_temp_c := %s,
                    p_raw := %s
                ) AS id
                """,
                (
                    body.device_serial, body.recorded_at,
                    body.ph, body.ph_mv, body.ph_temp_c,
                    body.conductivity_us_cm, body.salinity_ppt,
                    body.cond_temp_c, body.tds_mg_l,
                    body.do_mg_l, body.do_sat_pct, body.do_temp_c,
                    Json(body.raw) if body.raw is not None else None,
                ),
            )
            reading_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT id, device_serial, recorded_at, temp_c FROM shrimp.probe_readings WHERE id = %s",
                (reading_id,),
            )
            receipt = dict(cur.fetchone())
        conn.commit()
        return receipt
    except HTTPException:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        if exc.pgcode == "22023":
            raise HTTPException(status_code=409, detail="Device must be active and bound to a pond") from exc
        if exc.pgcode and exc.pgcode.startswith("22"):
            raise HTTPException(status_code=422, detail="Sensor value is outside the database format or range") from exc
        logger.exception("Probe reading ingestion failed")
        raise HTTPException(status_code=503, detail="Unable to store reading; retry later") from exc
