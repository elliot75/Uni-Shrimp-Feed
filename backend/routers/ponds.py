from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from access import get_pond_or_404, require_farmer_access, require_pond_access, visible_pond_filter
from alerts import evaluate_lab_test
from auth import get_current_user
from db import get_db
from models import CycleCreate, CycleUpdate, LabTestCreate, PondCreate, PondUpdate

router = APIRouter(prefix="/api", tags=["ponds"])

RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _clean(row) -> dict:
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat") and not isinstance(v, str):
            d[k] = v.isoformat()
        elif isinstance(v, (int, float)) or v is None or isinstance(v, bool) or isinstance(v, str):
            continue
        else:
            d[k] = float(v) if hasattr(v, "__float__") else v
    return d


def _cycle_doc(cycle: dict | None) -> dict | None:
    if not cycle:
        return None
    d = _clean(cycle)
    if cycle.get("stocked_at"):
        stocked = cycle["stocked_at"]
        from datetime import date
        if hasattr(stocked, "year") and not hasattr(stocked, "hour"):
            d["doc"] = (date.today() - stocked).days
        else:
            d["doc"] = None
    else:
        d["doc"] = None
    return d


@router.get("/ponds")
def list_ponds(current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    where, args = visible_pond_filter(current_user, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT p.*, u.display_name AS farmer_name, u.username AS farmer_username,
                   c.id AS cycle_id, c.stage AS cycle_stage, c.status AS cycle_status,
                   c.stocked_at, c.stocked_count, c.density_per_m2, c.sample_avg_weight_g,
                   (SELECT count(*) FROM shrimp.alert_events ae
                    WHERE ae.pond_id = p.id AND ae.resolved_at IS NULL) AS open_alerts
            FROM shrimp.ponds p
            JOIN shrimp.users u ON u.id = p.farmer_id
            LEFT JOIN shrimp.cycles c ON c.pond_id = p.id AND c.status = 'active'
            WHERE {where}
            ORDER BY p.code
            """,
            args,
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        item = _clean(r)
        item["cycle"] = None
        if r.get("cycle_id"):
            item["cycle"] = _cycle_doc({
                "id": r["cycle_id"],
                "stage": r["cycle_stage"],
                "status": r["cycle_status"],
                "stocked_at": r["stocked_at"],
                "stocked_count": r["stocked_count"],
                "density_per_m2": r["density_per_m2"],
                "sample_avg_weight_g": r["sample_avg_weight_g"],
            })
        out.append(item)
    return out


@router.post("/ponds")
def create_pond(body: PondCreate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    require_farmer_access(current_user, body.farmer_id, conn)
    if current_user["role"] == "farmer" and str(body.farmer_id) != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute(
                """
                INSERT INTO shrimp.ponds (
                    farmer_id, code, name, pond_type, area_m2, depth_m, volume_m3, location_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(body.farmer_id), body.code, body.name, body.pond_type,
                    body.area_m2, body.depth_m, body.volume_m3, body.location_text,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    return _clean(row)


@router.get("/ponds/{pond_id}")
def get_pond(pond_id: UUID, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM shrimp.cycles WHERE pond_id = %s AND status = 'active' LIMIT 1",
            (str(pond_id),),
        )
        cycle = cur.fetchone()
        cur.execute(
            """
            SELECT * FROM shrimp.probe_readings
            WHERE pond_id = %s ORDER BY recorded_at DESC LIMIT 1
            """,
            (str(pond_id),),
        )
        latest = cur.fetchone()
        cur.execute(
            """
            SELECT * FROM shrimp.alert_events
            WHERE pond_id = %s AND resolved_at IS NULL
            ORDER BY opened_at DESC
            """,
            (str(pond_id),),
        )
        alerts = cur.fetchall()
        cur.execute("SELECT * FROM shrimp.devices WHERE pond_id = %s", (str(pond_id),))
        devices = cur.fetchall()
        cur.execute("SELECT display_name, username FROM shrimp.users WHERE id = %s", (pond["farmer_id"],))
        farmer = cur.fetchone()
    item = _clean(pond)
    item["farmer_name"] = farmer["display_name"] if farmer else None
    item["farmer_username"] = farmer["username"] if farmer else None
    item["cycle"] = _cycle_doc(dict(cycle) if cycle else None)
    item["latest_reading"] = _clean(latest) if latest else None
    item["open_alerts"] = [_clean(a) for a in alerts]
    item["devices"] = [_clean(d) for d in devices]
    return item


@router.patch("/ponds/{pond_id}")
def update_pond(pond_id: UUID, body: PondUpdate, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    fields = body.model_dump(exclude_unset=True)
    if "farmer_id" in fields:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admin can reassign ponds")
        fields["farmer_id"] = str(fields["farmer_id"])
    if not fields:
        return _clean(pond)
    sets = [f"{k} = %s" for k in fields]
    args = list(fields.values()) + [str(pond_id)]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE shrimp.ponds SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    conn.commit()
    return _clean(row)


@router.get("/ponds/{pond_id}/readings")
def pond_readings(
    pond_id: UUID,
    range: str = Query("24h"),
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    hours = RANGE_HOURS.get(range, 24)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT recorded_at, ph, ph_temp_c, salinity_ppt, cond_temp_c,
                   conductivity_us_cm, tds_mg_l, do_mg_l, do_sat_pct, do_temp_c
            FROM shrimp.probe_readings
            WHERE pond_id = %s AND recorded_at >= %s
            ORDER BY recorded_at
            """,
            (str(pond_id), since),
        )
        rows = cur.fetchall()
    return [_clean(r) for r in rows]


@router.get("/ponds/{pond_id}/lab-tests")
def list_lab_tests(pond_id: UUID, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT lt.*, u.display_name AS recorded_by_name
            FROM shrimp.lab_tests lt
            LEFT JOIN shrimp.users u ON u.id = lt.recorded_by
            WHERE lt.pond_id = %s
            ORDER BY lt.sampled_at DESC
            LIMIT 200
            """,
            (str(pond_id),),
        )
        rows = cur.fetchall()
    return [_clean(r) for r in rows]


@router.post("/ponds/{pond_id}/lab-tests")
def create_lab_test(
    pond_id: UUID,
    body: LabTestCreate,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id FROM shrimp.cycles WHERE pond_id = %s AND status = 'active' LIMIT 1",
            (str(pond_id),),
        )
        cycle = cur.fetchone()
        cur.execute(
            """
            INSERT INTO shrimp.lab_tests (
                pond_id, cycle_id, sampled_at, no2_ppm, nh3_ppm, alkalinity_ppm,
                ca_ppm, mg_ppm, k_ppm, notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                str(pond_id),
                str(cycle["id"]) if cycle else None,
                body.sampled_at,
                body.no2_ppm, body.nh3_ppm, body.alkalinity_ppm,
                body.ca_ppm, body.mg_ppm, body.k_ppm, body.notes, current_user["id"],
            ),
        )
        row = dict(cur.fetchone())
    evaluate_lab_test(conn, row)
    conn.commit()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM shrimp.lab_tests WHERE id = %s", (row["id"],))
        saved = cur.fetchone()
    return _clean(saved)


@router.get("/ponds/{pond_id}/cycles")
def list_cycles(pond_id: UUID, current_user: dict = Depends(get_current_user), conn=Depends(get_db)):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM shrimp.cycles WHERE pond_id = %s ORDER BY created_at DESC",
            (str(pond_id),),
        )
        rows = cur.fetchall()
    return [_cycle_doc(dict(r)) for r in rows]


@router.post("/ponds/{pond_id}/cycles")
def create_cycle(
    pond_id: UUID,
    body: CycleCreate,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    pond = get_pond_or_404(conn, str(pond_id))
    require_pond_access(current_user, pond, conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if body.status == "active":
            cur.execute(
                "UPDATE shrimp.cycles SET status = 'harvested', updated_at = now() WHERE pond_id = %s AND status = 'active'",
                (str(pond_id),),
            )
        try:
            cur.execute(
                """
                INSERT INTO shrimp.cycles (
                    pond_id, status, stage, stocked_at, stocked_count, density_per_m2,
                    sample_avg_weight_g, species, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(pond_id), body.status, body.stage, body.stocked_at, body.stocked_count,
                    body.density_per_m2, body.sample_avg_weight_g, body.species, body.notes,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    return _cycle_doc(dict(row))


@router.patch("/cycles/{cycle_id}")
def update_cycle(
    cycle_id: UUID,
    body: CycleUpdate,
    current_user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM shrimp.cycles WHERE id = %s", (str(cycle_id),))
        cycle = cur.fetchone()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    pond = get_pond_or_404(conn, cycle["pond_id"])
    require_pond_access(current_user, pond, conn)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return _cycle_doc(dict(cycle))
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if fields.get("status") == "active":
            cur.execute(
                "UPDATE shrimp.cycles SET status = 'harvested', updated_at = now() WHERE pond_id = %s AND status = 'active' AND id <> %s",
                (str(cycle["pond_id"]), str(cycle_id)),
            )
        sets = [f"{k} = %s" for k in fields]
        args = list(fields.values()) + [str(cycle_id)]
        cur.execute(
            f"UPDATE shrimp.cycles SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
            args,
        )
        row = cur.fetchone()
    conn.commit()
    return _cycle_doc(dict(row))
