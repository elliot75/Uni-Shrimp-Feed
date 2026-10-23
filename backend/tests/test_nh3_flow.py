"""Real PostgreSQL queries + alert/API/React regressions, with no database server.

Setup: npm ci (repo root), npm --prefix frontend ci, pip install -r requirements.txt.
Only the in-memory WASM database is used; psycopg2 connections are forbidden.
"""
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alerts
from auth import get_current_user
from db import get_db
from embedded_postgres import EmbeddedPostgres, ROOT
from lab_samples import load_sample_conditions
from routers import ponds

POND = "00000000-0000-0000-0000-000000000001"
CYCLE = "00000000-0000-0000-0000-000000000002"
OTHER = "00000000-0000-0000-0000-000000000003"
LAB = "00000000-0000-0000-0000-000000000004"
SAMPLE = datetime(2026, 10, 1, 17, 15, tzinfo=timezone.utc)  # 00:15 in Vietnam
RULES = {
    code: {"code": code, "max_value": threshold}
    for code, threshold in (("NH3_WARN", 0.05), ("NH3_DANGER", 0.10), ("NH3_OUT_OF_RANGE", None))
}


def query(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture(scope="module")
def engine():
    conn = EmbeddedPostgres()
    try:
        # Relevant columns use the production types; no real schema is touched.
        statements = [
            "CREATE SCHEMA shrimp",
            "CREATE TABLE shrimp.users (id uuid PRIMARY KEY, display_name text)",
            """CREATE TABLE shrimp.probe_readings (
                id bigint PRIMARY KEY, pond_id uuid, cycle_id uuid, recorded_at timestamptz,
                ph numeric(4,2), do_temp_c numeric(6,2), salinity_ppt numeric(8,3), do_mg_l numeric,
                ph_temp_c numeric(6,2), cond_temp_c numeric(6,2),
                alerts_evaluated_at timestamptz)""",
            """CREATE TABLE shrimp.lab_tests (
                id uuid PRIMARY KEY, pond_id uuid, cycle_id uuid, sampled_at timestamptz,
                created_at timestamptz DEFAULT now(), recorded_by uuid,
                nh3_ppm numeric(10,3), nh3_unionized_ppm numeric(10,4),
                no2_ppm numeric, alkalinity_ppm numeric, ca_ppm numeric, mg_ppm numeric, k_ppm numeric)""",
            "CREATE TABLE shrimp.nh3_lookup (tan_ppm numeric, ph numeric, nh3_ppm numeric)",
        ]
        for sql in statements:
            query(conn, sql)
        # Use the real handbook data, not a second table maintained by tests.
        seed = (ROOT / "backend/sql/001_init.sql").read_text()
        table = re.search(r"INSERT INTO shrimp.nh3_lookup .*?ON CONFLICT DO NOTHING;", seed, re.S)
        query(conn, table.group())
        yield conn
    finally:
        conn.close()


@pytest.fixture
def env(engine, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("These regressions must never connect to an external database")

    monkeypatch.setattr(psycopg2, "connect", forbidden)
    query(engine, "BEGIN")
    pond = {"id": POND, "pond_type": "growout", "farmer_id": OTHER}
    monkeypatch.setattr(alerts, "load_pond", lambda *args: pond)
    monkeypatch.setattr(alerts, "load_active_cycle", lambda *args: {"id": CYCLE, "stage": "growout"})
    monkeypatch.setattr(alerts, "load_rules", lambda *args: RULES)
    monkeypatch.setattr(ponds, "get_pond_or_404", lambda *args: pond)
    upsert, resolve = Mock(), Mock()
    monkeypatch.setattr(alerts, "upsert_alert", upsert)
    monkeypatch.setattr(alerts, "resolve_alert", resolve)
    app = FastAPI()
    app.include_router(ponds.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": OTHER, "role": "admin"}
    app.dependency_overrides[get_db] = lambda: engine
    with TestClient(app) as client:
        yield engine, client, upsert, resolve
    query(engine, "ROLLBACK")


def probe(conn, ident, minutes=0, *, at=None, pond=POND, cycle=CYCLE, ph=None,
          temp=None, salt=None, ph_temp=None, cond_temp=None):
    query(conn, """INSERT INTO shrimp.probe_readings
        (id, pond_id, cycle_id, recorded_at, ph, do_temp_c, salinity_ppt, ph_temp_c, cond_temp_c)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (ident, pond, cycle, at or SAMPLE - timedelta(minutes=minutes), ph, temp, salt, ph_temp, cond_temp))


def lab(conn, *, tan=1, cycle=CYCLE, sample=SAMPLE, ident=LAB, saved=9):
    return query(conn, """INSERT INTO shrimp.lab_tests
        (id, pond_id, cycle_id, sampled_at, nh3_ppm, nh3_unionized_ppm)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (ident, POND, cycle, sample, tan, saved))[0]


def api_row(client, ident=LAB):
    response = client.get(f"/api/ponds/{POND}/lab-tests")
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["id"] == ident)


def assert_consistent(env, sample, expected, status, firing=None):
    conn, client, upsert, _ = env
    alerts.evaluate_lab_test(conn, sample)
    row = api_row(client, sample["id"])
    assert row["nh3_status"] == status
    stored = query(conn, "SELECT nh3_unionized_ppm FROM shrimp.lab_tests WHERE id = %s", (sample["id"],))[0]["nh3_unionized_ppm"]
    if expected is None:
        assert row["nh3_unionized_ppm"] is None and stored is None
    else:
        assert row["nh3_unionized_ppm"] == pytest.approx(expected, abs=0.00005)
        assert float(stored) == row["nh3_unionized_ppm"]
    codes = [call.args[3]["code"] for call in upsert.call_args_list]
    assert codes == ([firing] if firing else [])
    if firing and expected is not None:
        assert upsert.call_args.args[4] == pytest.approx(expected, abs=0.00005)
    return row


def render(rows):
    result = subprocess.run(
        ["node", "tests/render-lab-nh3.mjs"], cwd=ROOT / "frontend",
        input=json.dumps(rows), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_split_fields_flow_through_alert_api_and_react(env):
    conn, _, upsert, _ = env
    probe(conn, 1, 55, ph=8)
    probe(conn, 2, 40, temp=25)
    probe(conn, 3, 5, salt=15)
    probe(conn, 4, 1)  # Empty latest payload must not erase any field.
    row = assert_consistent(env, lab(conn), 0.0487, "temperature_adjusted")
    assert row["sample_ph"] == 8 and row["sample_temp_c"] == 25 and row["sample_salinity_ppt"] == 15
    for field, minutes in (("sample_ph", 55), ("sample_temp_c", 40), ("sample_salinity_ppt", 5)):
        assert datetime.fromisoformat(row[field + "_recorded_at"]) == SAMPLE - timedelta(minutes=minutes)
    assert row["nh3_handbook_ppm"] == 0.05
    assert row["nh3_salinity_adjusted"] is True
    for html in render([{"row": row, "locale": locale} for locale in ("zh-TW", "vi")]):
        assert '>0.05</td>' in html  # handbook stays separate
        assert f'>{row["nh3_unionized_ppm"]}</td>' in html
        assert '9</td>' not in html  # no stale stored value
        assert 'pH: 8' in html and '25 °C' in html and '15 ppt' in html


@pytest.mark.parametrize("temp,salt,expected,status,firing", [
    (25, None, 0.0537, "temperature_adjusted", "NH3_WARN"),
    (25, 0, 0.0537, "temperature_adjusted", "NH3_WARN"),
    (25, 999, 0.0537, "temperature_adjusted", "NH3_WARN"),
    (None, 15, 0.05, "handbook", "NH3_WARN"),
    (-0.01, 15, 0.05, "handbook", "NH3_WARN"),
    (40.01, 15, 0.05, "handbook", "NH3_WARN"),
    (40, None, 0.1347, "temperature_adjusted", "NH3_DANGER"),
    (0, None, 0.0082, "temperature_adjusted", None),
])
def test_fallbacks_preserve_formula_limits_and_thresholds(env, temp, salt, expected, status, firing):
    conn = env[0]
    probe(conn, 1, ph=8, temp=temp, salt=salt, ph_temp=30, cond_temp=30)
    row = assert_consistent(env, lab(conn), expected, status, firing)
    assert row["nh3_salinity_adjusted"] is False


@pytest.mark.parametrize("tan,ph,expected,status,firing", [
    (10, 9, 3.6186, "temperature_adjusted", "NH3_DANGER"),
    (10.001, 8, None, "outside_handbook", "NH3_OUT_OF_RANGE"),
    (1, 9.01, None, "outside_handbook", "NH3_OUT_OF_RANGE"),
    (0, 9.01, None, "outside_handbook", "NH3_OUT_OF_RANGE"),
    (1, None, None, "missing_ph", "NH3_OUT_OF_RANGE"),
    (0, 8, 0, "temperature_adjusted", None),
    (None, 8, None, "missing_tan", None),
])
def test_handbook_gate_and_missing_inputs_match_in_ui(env, tan, ph, expected, status, firing):
    conn = env[0]
    probe(conn, 1, ph=ph, temp=25)
    row = assert_consistent(env, lab(conn, tan=tan, saved=None), expected, status, firing)
    html, = render([{"row": row}])
    if status == "outside_handbook":
        assert '超出手冊表</td>' in html
        assert '僅供參考，不作為判定值' in html
    elif status == "missing_ph":
        assert '採樣前一小時內缺少 pH' in html
        assert '未作水溫修正' not in html
    elif status == "missing_tan":
        assert '未作水溫修正' not in html


def test_inclusive_sample_window_cycle_scope_and_ties(env):
    conn = env[0]
    probe(conn, 1, 60, ph=8, temp=25, salt=15)
    probe(conn, 2, 60.000001, ph=9, temp=35, salt=30)  # too old
    probe(conn, 3, -0.000001, ph=9, temp=35, salt=30)  # after sample
    probe(conn, 4, 0, cycle=OTHER, ph=9, temp=35, salt=30)
    probe(conn, 5, 0, cycle=None, ph=9, temp=35, salt=30)
    probe(conn, 6, 0, pond=OTHER, ph=9, temp=35, salt=30)
    probe(conn, 7, 0, ph=7.5)
    probe(conn, 8, 0, ph=8)  # same instant, greater id wins
    row = assert_consistent(env, lab(conn), 0.0487, "temperature_adjusted")
    assert row["sample_ph_recorded_at"] == SAMPLE.isoformat()
    assert datetime.fromisoformat(row["sample_temp_c_recorded_at"]) == SAMPLE - timedelta(hours=1)


@pytest.mark.parametrize("cycle", [None, OTHER])
def test_null_and_historical_cycles_never_drive_current_alerts(env, cycle):
    conn, _, _, resolve = env
    probe(conn, 1, cycle=cycle, ph=8, temp=25)
    probe(conn, 2, cycle=CYCLE, ph=9, temp=35)
    row = assert_consistent(env, lab(conn, cycle=cycle), 0.0537, "temperature_adjusted")
    assert row["sample_ph"] == 8
    resolve.assert_not_called()


def test_no_matching_cycle_or_time_never_reuses_saved_value(env):
    conn, client, _, _ = env
    probe(conn, 1, 60.001, ph=8, temp=25)
    probe(conn, 2, cycle=OTHER, ph=8, temp=25)
    sample = lab(conn)
    # GET recomputes from its own snapshot and remains read-only.
    row = api_row(client)
    assert row["nh3_handbook_ppm"] is None and row["nh3_unionized_ppm"] is None
    assert query(conn, "SELECT nh3_unionized_ppm FROM shrimp.lab_tests")[0]["nh3_unionized_ppm"] == 9
    assert_consistent(env, sample, None, "missing_ph", "NH3_OUT_OF_RANGE")


def test_future_cap_is_inclusive_and_missing_sample_never_searches_unbounded(env):
    conn, client, _, _ = env
    now = query(conn, "SELECT now() AS t")[0]["t"]
    sample = now + timedelta(minutes=6)
    probe(conn, 1, at=now + timedelta(minutes=5), ph=8, temp=25)
    probe(conn, 2, at=now + timedelta(minutes=5, milliseconds=1), ph=9, temp=35)
    lab(conn, sample=sample)
    conditions = load_sample_conditions(conn, POND, sample, CYCLE)
    row = api_row(client)
    assert row["sample_ph"] == conditions["sample_ph"] == 8
    assert row["sample_temp_c"] == conditions["sample_temp_c"] == 25
    assert all(v is None for v in load_sample_conditions(conn, POND, None, CYCLE).values())


@pytest.mark.parametrize("field,value", [("do_temp_c", 25), ("salinity_ppt", 15)])
def test_temperature_or_salinity_only_backfill_refreshes_tan(env, field, value):
    conn, client, upsert, resolve = env
    probe(conn, 1, 40, ph=8, temp=None if field == "do_temp_c" else 25)
    sample = lab(conn)
    alerts.evaluate_lab_test(conn, sample)
    before = api_row(client)["nh3_unionized_ppm"]
    upsert.reset_mock()
    resolve.reset_mock()
    probe(conn, 2, 20, temp=value if field == "do_temp_c" else None,
          salt=value if field == "salinity_ppt" else None)
    reading = query(conn, "SELECT * FROM shrimp.probe_readings WHERE id = 2")[0]
    alerts.evaluate_probe_reading(conn, reading)
    row = api_row(client)
    assert row["nh3_unionized_ppm"] != before
    saved = query(conn, "SELECT nh3_unionized_ppm FROM shrimp.lab_tests")[0]["nh3_unionized_ppm"]
    assert row["nh3_unionized_ppm"] == float(saved)
    assert query(conn, "SELECT alerts_evaluated_at FROM shrimp.probe_readings WHERE id = 2")[0]["alerts_evaluated_at"] is not None
    if field == "salinity_ppt":
        upsert.assert_not_called()
        assert any(c.args[-1] == "NH3_WARN" for c in resolve.call_args_list)


def test_latest_temperature_does_not_erase_earlier_salinity(env):
    conn = env[0]
    probe(conn, 1, 55, salt=15)
    probe(conn, 2, 40, ph=8)
    probe(conn, 3, 5, temp=25)
    assert_consistent(env, lab(conn), 0.0487, "temperature_adjusted")


def test_older_lab_in_active_cycle_is_calculated_without_changing_alerts(env):
    conn, _, _, resolve = env
    probe(conn, 1, ph=8, temp=25)
    older = lab(conn)
    lab(conn, ident=OTHER, sample=SAMPLE + timedelta(days=1))
    assert_consistent(env, older, 0.0537, "temperature_adjusted")
    resolve.assert_not_called()


def test_unassigned_lab_can_drive_alerts_when_there_is_no_active_cycle(env, monkeypatch):
    conn = env[0]
    monkeypatch.setattr(alerts, "load_active_cycle", lambda *args: None)
    probe(conn, 1, cycle=None, ph=8, temp=25)
    assert_consistent(env, lab(conn, cycle=None), 0.0537, "temperature_adjusted", "NH3_WARN")


def test_missing_handbook_never_uses_formula_as_threshold(env):
    conn = env[0]
    query(conn, "DELETE FROM shrimp.nh3_lookup")
    probe(conn, 1, ph=8, temp=25)
    row = assert_consistent(env, lab(conn), None, "missing_lookup", "NH3_OUT_OF_RANGE")
    assert row["nh3_emerson_ppm"] == 0.0537
    html, = render([{"row": row}])
    assert '缺少手冊表</td>' in html


def test_below_handbook_uses_lowest_cell_without_extrapolation(env):
    conn = env[0]
    probe(conn, 1, ph=6.5)
    row = assert_consistent(env, lab(conn, tan=0.1), 0, "handbook")
    assert row["nh3_handbook_ppm"] == 0


def test_display_rounding_does_not_change_alert_threshold(env):
    conn = env[0]
    probe(conn, 1, ph=8, temp=25)
    # 0.931 * the freshwater fraction is 0.04998..., displayed as 0.0500.
    # The threshold comparison must still use the unrounded number (< 0.05).
    assert_consistent(env, lab(conn, tan=0.931), 0.05, "temperature_adjusted")


def test_zero_tan_does_not_claim_invalid_temperature_correction(env):
    conn = env[0]
    probe(conn, 1, ph=8, temp=45)
    row = assert_consistent(env, lab(conn, tan=0), 0, "handbook")
    assert row["nh3_temp_adjusted"] is False
