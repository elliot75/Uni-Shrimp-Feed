"""Integration tests against UPVN_SHRIMP. Uses __test_ prefix rows and deletes them."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv
from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
DEVICE_URL = os.getenv("SHRIMP_DEVICE_URL")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Keep integration fixtures away from real devices registered in the shared database.
SERIAL = "A1B2C3D4E5F6"
FARMER_USER = "__test_farmer"
POND_CODE = "__TEST-P1"


def _admin():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def _cleanup(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM shrimp.probe_readings WHERE device_serial = %s", (SERIAL,))
    cur.execute("DELETE FROM shrimp.devices WHERE serial = %s", (SERIAL,))
    cur.execute("DELETE FROM shrimp.cycles WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code = %s)", (POND_CODE,))
    cur.execute("DELETE FROM shrimp.alert_events WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code = %s)", (POND_CODE,))
    cur.execute("DELETE FROM shrimp.ponds WHERE code = %s", (POND_CODE,))
    cur.execute("DELETE FROM shrimp.users WHERE username = %s", (FARMER_USER,))
    cur.close()


@pytest.fixture
def setup_device():
    if not DATABASE_URL or not DEVICE_URL:
        pytest.skip("DATABASE_URL / SHRIMP_DEVICE_URL missing")
    conn = _admin()
    _cleanup(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO shrimp.users (username, email, password_hash, role, display_name, locale)
        VALUES (%s, %s, %s, 'farmer', 'Test Farmer', 'vi')
        RETURNING id
        """,
        (FARMER_USER, "test-farmer@example.com", pwd.hash("testpass12")),
    )
    farmer_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO shrimp.ponds (farmer_id, code, name, pond_type)
        VALUES (%s, %s, 'Test Pond', 'growout')
        RETURNING id
        """,
        (farmer_id, POND_CODE),
    )
    pond_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO shrimp.devices (serial, pond_id, name)
        VALUES (%s, %s, 'ESP32 test')
        """,
        (SERIAL, pond_id),
    )
    cur.close()
    yield {"pond_id": pond_id, "farmer_id": farmer_id}
    _cleanup(conn)
    conn.close()


def test_ingest_sample_and_idempotent(setup_device):
    conn = psycopg2.connect(DEVICE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    sql = """
        SELECT shrimp.ingest_probe_reading(
            p_device_serial := %s,
            p_recorded_at := TIMESTAMPTZ '2026-09-12 17:30:00+07',
            p_ph := 9.01,
            p_ph_mv := -65.68,
            p_ph_temp_c := 25.10,
            p_conductivity_us_cm := 29642.26,
            p_salinity_ppt := 18.33,
            p_cond_temp_c := 26.10,
            p_tds_mg_l := 18971.04,
            p_do_mg_l := NULL,
            p_do_sat_pct := NULL,
            p_do_temp_c := NULL,
            p_raw := NULL
        )
    """
    cur.execute(sql, (SERIAL,))
    first = cur.fetchone()[0]
    cur.execute(sql, (SERIAL,))
    second = cur.fetchone()[0]
    assert first == second
    admin = _admin()
    acur = admin.cursor()
    acur.execute("SELECT count(*) FROM shrimp.probe_readings WHERE device_serial = %s", (SERIAL,))
    assert acur.fetchone()[0] == 1
    acur.execute("SELECT ph, salinity_ppt, pond_id FROM shrimp.probe_readings WHERE id = %s", (first,))
    ph, sal, pond_id = acur.fetchone()
    assert float(ph) == 9.01
    assert float(sal) == 18.33
    assert pond_id == setup_device["pond_id"]
    acur.close()
    admin.close()
    cur.close()
    conn.close()


def test_unknown_serial_fails(setup_device):
    conn = psycopg2.connect(DEVICE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    with pytest.raises(psycopg2.Error):
        cur.execute(
            """
            SELECT shrimp.ingest_probe_reading(
                p_device_serial := 'NO-SUCH-DEVICE',
                p_recorded_at := TIMESTAMPTZ '2026-09-12 17:30:00+07'
            )
            """
        )
    cur.close()
    conn.close()


def test_device_role_cannot_select_users(setup_device):
    conn = psycopg2.connect(DEVICE_URL)
    cur = conn.cursor()
    with pytest.raises(psycopg2.Error):
        cur.execute("SELECT count(*) FROM shrimp.users")
    cur.close()
    conn.close()
