from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from access import visible_pond_filter
from auth import get_current_user, require_admin
from db import get_db
from models import AlertRuleUpdate

router = APIRouter(prefix="/api", tags=["alerts"])


def _clean(row) -> dict:
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat") and not isinstance(v, str):
            d[k] = v.isoformat()
    return d


@router.get("/alerts")
def list_alerts(
    status: str = "open",
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    where, args = visible_pond_filter(current_user, conn)
    extra = "AND ae.resolved_at IS NULL" if status != "all" else ""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT ae.*, p.code AS pond_code, p.name AS pond_name
            FROM shrimp.alert_events ae
            JOIN shrimp.ponds p ON p.id = ae.pond_id
            WHERE {where} {extra}
            ORDER BY ae.opened_at DESC
            LIMIT 300
            """,
            args,
        )
        rows = cur.fetchall()
    return [_clean(r) for r in rows]


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: UUID, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    where, args = visible_pond_filter(current_user, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT ae.* FROM shrimp.alert_events ae
            JOIN shrimp.ponds p ON p.id = ae.pond_id
            WHERE ae.id = %s AND {where}
            """,
            [str(alert_id), *args],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        cur.execute(
            """
            UPDATE shrimp.alert_events
            SET acknowledged_at = now(), acknowledged_by = %s
            WHERE id = %s
            RETURNING *
            """,
            (current_user["id"], str(alert_id)),
        )
        saved = cur.fetchone()
    conn.commit()
    return _clean(saved)


@router.get("/alert-rules")
def list_rules(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM shrimp.alert_rules ORDER BY sort_order, code")
        rows = cur.fetchall()
    return [_clean(r) for r in rows]


@router.patch("/alert-rules/{rule_id}")
def update_rule(rule_id: UUID, body: AlertRuleUpdate, admin: dict = Depends(require_admin), conn=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields")
    sets = [f"{k} = %s" for k in fields]
    args = list(fields.values()) + [str(rule_id)]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM shrimp.alert_rules WHERE id = %s FOR UPDATE", (str(rule_id),))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Rule not found")
        updated = dict(existing) | fields
        code = updated["code"]
        threshold = "min_value" if "LOW" in code or code == "DO_CRITICAL" else "max_value"
        if updated.get(threshold) is None:
            raise HTTPException(status_code=422, detail=f"{code} requires {threshold}")
        if code == "DEVICE_STALE" and updated[threshold] < 1:
            raise HTTPException(status_code=422, detail="DEVICE_STALE must be at least 1 minute")
        if any(key in fields and fields[key] is None for key in ("severity", "is_active")):
            raise HTTPException(status_code=422, detail="severity and is_active cannot be null")
        cur.execute(
            f"UPDATE shrimp.alert_rules SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    conn.commit()
    return _clean(row)
