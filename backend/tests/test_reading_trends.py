"""Run trend SQL against an isolated in-memory PostgreSQL database."""
from datetime import date
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_current_user
from db import get_db
from embedded_postgres import EmbeddedPostgres
from reading_trends import TREND_FIELDS, TREND_MAX_POINTS
from routers import ponds

POND = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def trend_api(monkeypatch):
    conn = EmbeddedPostgres()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA shrimp")
            cur.execute("""
                CREATE TABLE shrimp.probe_readings (
                    id bigint PRIMARY KEY, pond_id uuid, recorded_at timestamptz,
                    ph numeric, ph_mv numeric, salinity_ppt numeric, do_mg_l numeric,
                    temp_c numeric, ph_temp_c numeric, cond_temp_c numeric,
                    conductivity_us_cm numeric, tds_mg_l numeric,
                    do_sat_pct numeric, do_temp_c numeric
                )
            """)
        monkeypatch.setattr(ponds, "get_pond_or_404", lambda *args: {"farmer_id": "qa"})
        app = FastAPI()
        app.include_router(ponds.router)
        app.dependency_overrides[get_db] = lambda: conn
        app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
        with TestClient(app) as client:
            yield conn, client
    finally:
        conn.close()


def readings(client, **params):
    response = client.get(f"/api/ponds/{POND}/readings", params={"range": "all", **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_large_history_is_bounded_and_preserves_each_metric_extreme(trend_api):
    conn, client = trend_api
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shrimp.probe_readings
                (id, pond_id, recorded_at, ph, ph_mv, salinity_ppt, do_mg_l, temp_c)
            SELECT i, %s, '2024-01-01T00:00:00Z'::timestamptz + i * interval '30 minutes',
                   8, -50, 17, 6, 26
            FROM generate_series(1, 20000) i
        """, (str(POND),))
        # Different metrics peak on different rows within the same bucket.
        for index, field in enumerate(TREND_FIELDS):
            cur.execute(
                f"UPDATE shrimp.probe_readings SET {field} = 999 WHERE id = %s",
                (10001 + 2 * index,),
            )
            cur.execute(
                f"UPDATE shrimp.probe_readings SET {field} = -999 WHERE id = %s",
                (10002 + 2 * index,),
            )
    result = readings(client, trend=True)
    assert len(result) <= TREND_MAX_POINTS
    assert len(result) < 20000
    for field in TREND_FIELDS:
        assert min(row[field] for row in result) == -999
        assert max(row[field] for row in result) == 999
    assert result[0]["recorded_at"].startswith("2024-01-01T00:30")
    assert result[-1]["recorded_at"] > result[0]["recorded_at"]
    assert len(readings(client)) == 20000  # Existing raw API callers keep full rows.


def test_small_history_gaps_and_custom_date_boundaries(trend_api):
    conn, client = trend_api
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shrimp.probe_readings (id, pond_id, recorded_at, ph, do_mg_l)
            VALUES
                (1, %s, '2025-01-01T16:59:59Z', 8, 6),
                (2, %s, '2025-01-01T17:00:00Z', 9, 6),
                (3, %s, '2025-01-01T17:30:00Z', NULL, 6),
                (4, %s, '2025-01-01T18:00:00Z', 8, 6),
                (5, %s, '2025-01-02T16:59:59Z', 7, 6),
                (6, %s, '2025-01-02T17:00:00Z', 8, 6)
        """, (str(POND),) * 6)
    result = readings(client, trend=True, range="custom",
                      start_date=date(2025, 1, 2), end_date=date(2025, 1, 2))
    assert len(result) == 4
    assert result[0]["ph"] == 9
    assert result[-1]["ph"] == 7
    assert result[0]["segment_ph"] != result[2]["segment_ph"]
    assert result[0]["segment_do_mg_l"] == result[2]["segment_do_mg_l"]
    assert result[2]["segment_do_mg_l"] != result[3]["segment_do_mg_l"]
    assert readings(client, trend=True, range="custom",
                    start_date="2023-01-01", end_date="2023-01-01") == []


def test_single_timestamp_and_empty_history(trend_api):
    conn, client = trend_api
    assert readings(client, trend=True) == []
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shrimp.probe_readings (id, pond_id, recorded_at, ph)
            SELECT i, %s, '2025-01-01'::timestamptz, i FROM generate_series(1, 3) i
        """, (str(POND),))
    result = readings(client, trend=True)
    assert result[0]["ph"] == 1
    assert result[-1]["ph"] == 3
