from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from access import visible_pond_filter
from auth import get_current_user
from db import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _clean(row) -> dict:
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat") and not isinstance(v, str):
            d[k] = v.isoformat()
    return d


@router.get("")
def dashboard(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    where, args = visible_pond_filter(current_user, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT p.id, p.code, p.name, p.pond_type, p.farmer_id,
                   u.display_name AS farmer_name,
                   c.stage AS cycle_stage, c.stocked_at,
                   d.serial AS device_serial, d.last_seen_at,
                   r.recorded_at, r.ph, r.salinity_ppt, r.do_mg_l,
                   COALESCE(r.ph_temp_c, r.cond_temp_c, r.do_temp_c) AS temp_c,
                   (
                     SELECT count(*) FROM shrimp.alert_events ae
                     WHERE ae.pond_id = p.id AND ae.resolved_at IS NULL
                   ) AS open_alerts,
                   (
                     SELECT ae.severity FROM shrimp.alert_events ae
                     WHERE ae.pond_id = p.id AND ae.resolved_at IS NULL
                     ORDER BY CASE ae.severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END
                     LIMIT 1
                   ) AS worst_severity
            FROM shrimp.ponds p
            JOIN shrimp.users u ON u.id = p.farmer_id
            LEFT JOIN shrimp.cycles c ON c.pond_id = p.id AND c.status = 'active'
            LEFT JOIN LATERAL (
                SELECT * FROM shrimp.devices dv
                WHERE dv.pond_id = p.id AND dv.is_active = true
                ORDER BY dv.last_seen_at DESC NULLS LAST
                LIMIT 1
            ) d ON true
            LEFT JOIN LATERAL (
                SELECT * FROM shrimp.probe_readings pr
                WHERE pr.pond_id = p.id
                ORDER BY pr.recorded_at DESC
                LIMIT 1
            ) r ON true
            WHERE p.is_active = true AND {where}
            ORDER BY p.code
            """,
            args,
        )
        ponds = [_clean(r) for r in cur.fetchall()]
        cur.execute(
            f"""
            SELECT count(*) FILTER (WHERE ae.resolved_at IS NULL) AS open_count,
                   count(*) FILTER (WHERE ae.resolved_at IS NULL AND ae.severity = 'critical') AS critical_count
            FROM shrimp.alert_events ae
            JOIN shrimp.ponds p ON p.id = ae.pond_id
            WHERE {where}
            """,
            args,
        )
        stats = dict(cur.fetchone())
    return {"ponds": ponds, "stats": stats}
