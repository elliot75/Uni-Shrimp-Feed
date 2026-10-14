"""Exercise the review regressions against PostgreSQL, with rollback and no notifications."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import alerts
from db import get_connection
from models import CycleUpdate, LabTestCreate
from routers.ponds import _lab_cycle_id, get_pond, update_cycle
from routers.dashboard import dashboard


RULES = {
    "PH_HIGH": {"code": "PH_HIGH", "metric": "ph", "max_value": 7.8, "severity": "warn"},
    "DO_CRITICAL": {"code": "DO_CRITICAL", "metric": "do_mg_l", "min_value": 3, "severity": "critical"},
    "CA_LOW_GROWOUT": {"code": "CA_LOW_GROWOUT", "metric": "ca_ppm", "min_value": 160, "severity": "warn"},
    "NO2_HARVEST_EARLY": {"code": "NO2_HARVEST_EARLY", "metric": "no2_ppm", "max_value": 7, "severity": "critical"},
}


@pytest.fixture
def farm():
    conn = get_connection()
    now = datetime.now(timezone.utc)
    unique = uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO shrimp.users (username, email, password_hash, role, display_name)
                           VALUES (%s, %s, 'unused', 'farmer', 'review test') RETURNING id""",
                        (unique, unique + '@example.invalid'))
            user_id = cur.fetchone()["id"]
            cur.execute("""INSERT INTO shrimp.ponds (farmer_id, code, name, pond_type)
                           VALUES (%s, %s, 'review test', 'growout') RETURNING *""", (user_id, unique))
            pond = dict(cur.fetchone())
            cur.execute("""INSERT INTO shrimp.cycles (pond_id, status, stage, stocked_at)
                           VALUES (%s, 'active', 'growout', %s) RETURNING *""",
                        (pond["id"], now.date() - timedelta(days=40)))
            cycle = dict(cur.fetchone())
        with patch.object(alerts, "notify_alert"), patch.object(alerts, "load_rules", return_value=RULES):
            yield conn, pond, cycle, now
    finally:
        conn.rollback()
        conn.close()


def lab(conn, pond, cycle, sampled_at, **metrics):
    fields = list(metrics)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO shrimp.lab_tests (pond_id, cycle_id, sampled_at, {', '.join(fields)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(fields))}) RETURNING *",
            (pond["id"], cycle["id"], sampled_at, *metrics.values()),
        )
        return dict(cur.fetchone())


def probe(conn, pond, cycle, recorded_at, ph):
    serial = uuid4().hex[:12].upper()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO shrimp.devices (serial, pond_id) VALUES (%s, %s) RETURNING id", (serial, pond["id"]))
        device_id = cur.fetchone()["id"]
        cur.execute("""INSERT INTO shrimp.probe_readings (device_serial, device_id, pond_id, cycle_id, recorded_at, ph)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (serial, device_id, pond["id"], cycle["id"], recorded_at, ph))
        return dict(cur.fetchone())


def open_codes(conn, pond):
    with conn.cursor() as cur:
        cur.execute("SELECT rule_code FROM shrimp.alert_events WHERE pond_id = %s AND resolved_at IS NULL", (pond["id"],))
        return {row["rule_code"] for row in cur.fetchall()}


def test_future_lab_does_not_mask_real_warning(farm):
    conn, pond, cycle, now = farm
    lab(conn, pond, cycle, now + timedelta(days=365), ca_ppm=200)
    current = lab(conn, pond, cycle, now, ca_ppm=50)
    alerts.evaluate_lab_test(conn, current)
    assert "CA_LOW_GROWOUT" in open_codes(conn, pond)
    assert alerts._latest_lab_metrics(conn, pond["id"], cycle["id"])["ca_ppm"] == current["id"]


def test_same_time_old_probe_cannot_clear_selected_warning(farm):
    conn, pond, cycle, now = farm
    old = probe(conn, pond, cycle, now, 7.7)
    selected = probe(conn, pond, cycle, now, 9)
    alerts.evaluate_probe_reading(conn, selected)
    alerts.evaluate_probe_reading(conn, old)
    assert "PH_HIGH" in open_codes(conn, pond)
    assert alerts._latest_probe_metrics(conn, pond["id"])["ph"] == selected["id"]
    admin = {'id': str(pond['farmer_id']), 'role': 'admin'}
    assert get_pond(pond['id'], admin, conn)['latest_reading']['id'] == selected['id']
    assert next(p for p in dashboard(admin, conn)['ponds'] if p['id'] == str(pond['id']))['ph'] == 9


def test_same_time_old_lab_cannot_clear_selected_warning(farm):
    conn, pond, cycle, now = farm
    old = lab(conn, pond, cycle, now, ca_ppm=200)
    selected = lab(conn, pond, cycle, now, ca_ppm=50)
    with conn.cursor() as cur:
        cur.execute('UPDATE shrimp.lab_tests SET created_at = created_at - interval \'1 second\' WHERE id = %s', (old['id'],))
    alerts.evaluate_lab_test(conn, selected)
    alerts.evaluate_lab_test(conn, old)
    assert 'CA_LOW_GROWOUT' in open_codes(conn, pond)


def test_backfill_completes_and_breaks_no2_streak(farm):
    conn, pond, cycle, now = farm
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    rows = [lab(conn, pond, cycle, start + timedelta(days=day), no2_ppm=8) for day in range(7) if day != 3]
    alerts.evaluate_lab_test(conn, rows[-1])
    assert "NO2_HARVEST_EARLY" not in open_codes(conn, pond)
    missing = lab(conn, pond, cycle, start + timedelta(days=3), no2_ppm=8)
    alerts.evaluate_lab_test(conn, missing)
    assert "NO2_HARVEST_EARLY" in open_codes(conn, pond)
    corrected = lab(conn, pond, cycle, start + timedelta(days=3, hours=1), no2_ppm=1)
    alerts.evaluate_lab_test(conn, corrected)
    assert "NO2_HARVEST_EARLY" not in open_codes(conn, pond)


def test_historical_sample_uses_original_cycle_and_ph(farm):
    conn, pond, current_cycle, now = farm
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO shrimp.cycles (pond_id, status, stage, stocked_at, harvested_at)
                       VALUES (%s, 'harvested', 'growout', %s, %s) RETURNING *""",
                    (pond["id"], now.date() - timedelta(days=80), now.date() - timedelta(days=41)))
        old_cycle = dict(cur.fetchone())
    sampled = now - timedelta(days=50)
    body = LabTestCreate(sampled_at=sampled, nh3_ppm=1)
    assert _lab_cycle_id(conn, pond["id"], body) == old_cycle["id"]
    probe(conn, pond, old_cycle, sampled - timedelta(minutes=5), 8)
    historical = lab(conn, pond, old_cycle, sampled, nh3_ppm=1)
    alerts.evaluate_lab_test(conn, historical)
    with conn.cursor() as cur:
        cur.execute("SELECT nh3_unionized_ppm FROM shrimp.lab_tests WHERE id = %s", (historical["id"],))
        assert cur.fetchone()["nh3_unionized_ppm"] is not None
    assert not open_codes(conn, pond)
    with pytest.raises(HTTPException) as error:
        _lab_cycle_id(conn, pond["id"], LabTestCreate(sampled_at=sampled, cycle_id=current_cycle["id"]))
    assert error.value.status_code == 422


def test_cycle_choice_rejects_foreign_and_ambiguous_cycles(farm):
    conn, pond, cycle, now = farm
    with pytest.raises(HTTPException) as error:
        _lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now, cycle_id=uuid4()))
    assert error.value.status_code == 422
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO shrimp.cycles (pond_id, status, stage, stocked_at, harvested_at)
                       VALUES (%s, 'harvested', 'growout', %s, %s)""", (pond['id'], cycle['stocked_at'], now.date()))
    with pytest.raises(HTTPException) as error:
        _lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now))
    assert error.value.status_code == 422
    assert _lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now, cycle_id=cycle['id'])) == cycle['id']
    assert _lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now, cycle_id=None)) is None


def test_harvest_preserves_probe_alerts(farm):
    conn, pond, cycle, _ = farm
    for code in ("PH_HIGH", "DO_CRITICAL", "CA_LOW_GROWOUT"):
        alerts.upsert_alert(conn, pond, cycle, RULES[code], 1, 'test', 'test')

    class UncommittedConnection:
        def cursor(self, *args, **kwargs):
            return conn.cursor(*args, **kwargs)

        def commit(self):
            pass

    update_cycle(cycle["id"], CycleUpdate(status='harvested'), {'id': str(pond["farmer_id"]), 'role': 'admin'}, UncommittedConnection())
    assert open_codes(conn, pond) == {"PH_HIGH", "DO_CRITICAL"}


@pytest.mark.parametrize('sampled_at', [datetime.now(timezone.utc) + timedelta(days=1), datetime(2026, 1, 1)])
def test_invalid_sample_time_is_rejected(sampled_at):
    with pytest.raises(ValidationError):
        LabTestCreate(sampled_at=sampled_at)
