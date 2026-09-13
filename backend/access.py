"""Row-level access helpers."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException


def farmer_ids_for_salesperson(conn, salesperson_id: str) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT farmer_id FROM shrimp.salesperson_farmers WHERE salesperson_id = %s",
            (salesperson_id,),
        )
        return [row["farmer_id"] for row in cur.fetchall()]


def can_see_farmer(user: dict, farmer_id, conn) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "farmer":
        return str(farmer_id) == user["id"]
    if user["role"] == "salesperson":
        ids = {str(x) for x in farmer_ids_for_salesperson(conn, user["id"])}
        return str(farmer_id) in ids
    return False


def require_farmer_access(user: dict, farmer_id, conn) -> None:
    if not can_see_farmer(user, farmer_id, conn):
        raise HTTPException(status_code=403, detail="Forbidden")


def get_pond_or_404(conn, pond_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM shrimp.ponds WHERE id = %s", (pond_id,))
        pond = cur.fetchone()
    if not pond:
        raise HTTPException(status_code=404, detail="Pond not found")
    return dict(pond)


def require_pond_access(user: dict, pond, conn) -> None:
    require_farmer_access(user, pond["farmer_id"], conn)


def visible_pond_filter(user: dict, conn) -> tuple[str, list]:
    if user["role"] == "admin":
        return "TRUE", []
    if user["role"] == "farmer":
        return "p.farmer_id = %s", [user["id"]]
    ids = farmer_ids_for_salesperson(conn, user["id"])
    if not ids:
        return "FALSE", []
    return "p.farmer_id = ANY(%s::uuid[])", [ids]
