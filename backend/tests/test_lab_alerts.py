from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv
from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from alerts import evaluate_lab_test, process_pending_readings  # noqa: E402
from db import get_connection  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PREFIX = "__test_lab_"
SERIAL = "840D8E235165"


def _cleanup(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM shrimp.notification_log WHERE alert_event_id IN (SELECT id FROM shrimp.alert_events WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s))", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.alert_events WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.lab_tests WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.probe_readings WHERE device_serial = %s", (SERIAL,))
    cur.execute("DELETE FROM shrimp.devices WHERE serial = %s", (SERIAL,))
    cur.execute("DELETE FROM shrimp.cycles WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.ponds WHERE code LIKE %s", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.users WHERE username LIKE %s", (PREFIX + "%",))
    conn.commit()
    cur.close()


@pytest.fixture
def pond():
    conn = get_connection()
    _cleanup(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO shrimp.users (username, email, password_hash, role, display_name, locale)
        VALUES (%s, %s, %s, 'farmer', 'lab farmer', 'vi') RETURNING id
        """,
        (PREFIX + "farmer", PREFIX + "farmer@ex.com", pwd.hash("password12")),
    )
    farmer_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO shrimp.ponds (farmer_id, code, name, pond_type) VALUES (%s, %s, 'lab', 'growout') RETURNING id",
        (farmer_id, PREFIX + "P"),
    )
    pond_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO shrimp.devices (serial, pond_id, name) VALUES (%s, %s, 'd')",
        (SERIAL, pond_id),
    )
    conn.commit()
    cur.close()
    yield conn, pond_id
    _cleanup(conn)
    conn.close()


def test_ph_high_from_ingest(pond):
    conn, pond_id = pond
    cur = conn.cursor()
    cur.execute(
        """
        SELECT shrimp.ingest_probe_reading(
            p_device_serial := %s,
            p_recorded_at := %s,
            p_ph := 9.01,
            p_salinity_ppt := 18.33
        )
        """,
        (SERIAL, datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)),
    )
    conn.commit()
    process_pending_readings(conn)
    conn.commit()
    cur.execute(
        "SELECT rule_code FROM shrimp.alert_events WHERE pond_id = %s AND resolved_at IS NULL",
        (pond_id,),
    )
    codes = {r["rule_code"] for r in cur.fetchall()}
    cur.close()
    assert "PH_HIGH" in codes


def test_no2_seven_days_harvest(pond):
    conn, pond_id = pond
    cur = conn.cursor()
    last_id = None
    for i in range(7):
        sampled = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc) + timedelta(days=i)
        cur.execute(
            """
            INSERT INTO shrimp.lab_tests (pond_id, sampled_at, no2_ppm)
            VALUES (%s, %s, 7.5) RETURNING *
            """,
            (pond_id, sampled),
        )
        last_id = dict(cur.fetchone())
    conn.commit()
    # consecutive_no2_days uses date.today(); insert tests relative to today instead
    cur.execute("DELETE FROM shrimp.lab_tests WHERE pond_id = %s", (pond_id,))
    last = None
    today = datetime.now(timezone.utc).date()
    for i in range(7):
        sampled = datetime.combine(today - timedelta(days=6 - i), datetime.min.time()).replace(tzinfo=timezone.utc)
        cur.execute(
            """
            INSERT INTO shrimp.lab_tests (pond_id, sampled_at, no2_ppm)
            VALUES (%s, %s, 7.5) RETURNING *
            """,
            (pond_id, sampled),
        )
        last = dict(cur.fetchone())
    conn.commit()
    evaluate_lab_test(conn, last)
    conn.commit()
    cur.execute(
        "SELECT rule_code FROM shrimp.alert_events WHERE pond_id = %s AND resolved_at IS NULL",
        (pond_id,),
    )
    codes = {r["rule_code"] for r in cur.fetchall()}
    cur.close()
    assert "NO2_HIGH" in codes
    assert "NO2_HARVEST_EARLY" in codes
