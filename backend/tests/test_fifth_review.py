"""Fifth-review regressions; migrations run in a rollback-only isolated schema."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.responses import JSONResponse

import alerts
from db import get_connection
from models import CycleUpdate, LabTestCreate
from routers.ponds import _clean, _lab_cycle_id, update_cycle
from test_fourth_review import Uncommitted
from test_third_review import farm, lab, open_codes

SQL_DIR = Path(__file__).resolve().parents[1] / 'sql'
LAB_FIELDS = ('no2_ppm', 'nh3_ppm', 'alkalinity_ppm', 'ca_ppm', 'mg_ppm', 'k_ppm')


@pytest.mark.parametrize('field', LAB_FIELDS)
@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', -1])
def test_reject_invalid_lab_numbers(field, value):
    with pytest.raises(ValidationError):
        LabTestCreate(sampled_at=datetime.now(timezone.utc), **{field: value})


def test_invalid_input_preserves_warning(farm):
    conn, pond, cycle, now = farm
    alerts.evaluate_lab_test(conn, lab(conn, pond, cycle, now, ca_ppm=50))
    with pytest.raises(ValidationError):
        LabTestCreate(sampled_at=now, ca_ppm='NaN')
    assert 'CA_LOW_GROWOUT' in open_codes(conn, pond)
    assert LabTestCreate(sampled_at=now, ca_ppm=0).ca_ppm == 0


def test_reactivate_clears_harvest_and_accepts_new_samples(farm):
    conn, pond, cycle, now = farm
    user = {'role': 'admin', 'id': str(pond['farmer_id'])}
    update_cycle(cycle['id'], CycleUpdate(status='harvested', harvested_at=now.date()-timedelta(days=2)), user, Uncommitted(conn))
    result = update_cycle(cycle['id'], CycleUpdate(status='active'), user, Uncommitted(conn))
    assert result['harvested_at'] is None
    assert str(_lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now))) == str(cycle['id'])
    assert str(_lab_cycle_id(conn, pond['id'], LabTestCreate(sampled_at=now, cycle_id=cycle['id']))) == str(cycle['id'])
    alerts.evaluate_lab_test(conn, lab(conn, pond, cycle, now, ca_ppm=50))
    assert 'CA_LOW_GROWOUT' in open_codes(conn, pond)
    for body in (CycleUpdate(status='active', harvested_at=now.date()), CycleUpdate(harvested_at=now.date())):
        with pytest.raises(HTTPException) as exc:
            update_cycle(cycle['id'], body, user, Uncommitted(conn))
        assert exc.value.status_code == 422


@pytest.fixture
def isolated_schema():
    conn = get_connection()
    schema = 'review_' + uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA {schema}')
            for table in ('cycles', 'devices', 'probe_readings', 'lab_tests'):
                cur.execute(f'CREATE TABLE {schema}.{table} (LIKE shrimp.{table} INCLUDING ALL)')
            source = (SQL_DIR / '002_mac_device_identity.sql').read_text()
            normalize = source[source.index('CREATE OR REPLACE FUNCTION'):source.index('CREATE OR REPLACE FUNCTION shrimp.prevent')]
            cur.execute(normalize.replace('shrimp.', schema + '.'))
        yield conn, schema
    finally:
        conn.rollback()
        conn.close()


def apply_migration(conn, schema, filename):
    sql = (SQL_DIR / filename).read_text().replace('BEGIN;\n', '', 1).removesuffix('COMMIT;\n')
    sql = sql.replace('shrimp.', schema + '.').replace('search_path = shrimp,', f'search_path = {schema},')
    with conn.cursor() as cur:
        cur.execute(sql)


def test_lab_migration_preserves_values_and_blocks_invalid_writes(isolated_schema):
    conn, schema = isolated_schema
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {schema}.lab_tests (pond_id, sampled_at, ca_ppm, no2_ppm, nh3_ppm, nh3_unionized_ppm, k_ppm, notes) VALUES (%s, now(), 'NaN', -1, 'NaN', 0.2, 150, 'original note') RETURNING id", (str(uuid4()),))
        row_id = cur.fetchone()['id']
    apply_migration(conn, schema, '007_valid_lab_values.sql')
    apply_migration(conn, schema, '007_valid_lab_values.sql')
    with conn.cursor() as cur:
        cur.execute(f'SELECT * FROM {schema}.lab_tests WHERE id=%s', (row_id,))
        row = dict(cur.fetchone())
        assert row['ca_ppm'] is None and row['no2_ppm'] is None
        assert row['nh3_ppm'] is None and row['nh3_unionized_ppm'] is None
        assert row['k_ppm'] == 150
        assert 'original note' in row['notes'] and 'ca_ppm] NaN' in row['notes']
        assert row['notes'].count('ca_ppm] NaN') == 1
        JSONResponse(_clean(row))
        for field in (*LAB_FIELDS, 'nh3_unionized_ppm'):
            for bad in ('NaN', '-1'):
                cur.execute('SAVEPOINT invalid_value')
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cur.execute(f'UPDATE {schema}.lab_tests SET {field}=%s WHERE id=%s', (bad, row_id))
                cur.execute('ROLLBACK TO SAVEPOINT invalid_value')


def test_probe_ingest_assigns_by_date_and_repairs_history(isolated_schema):
    conn, schema = isolated_schema
    now = datetime.now(timezone.utc)
    pond_id, serial = str(uuid4()), uuid4().hex[:12].upper()
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {schema}.cycles (pond_id, status, stage, stocked_at, harvested_at) VALUES (%s, 'harvested', 'growout', %s, %s) RETURNING id", (pond_id, now.date()-timedelta(days=80), now.date()-timedelta(days=41)))
        old_cycle = cur.fetchone()['id']
        cur.execute(f"INSERT INTO {schema}.cycles (pond_id, status, stage, stocked_at) VALUES (%s, 'active', 'growout', %s) RETURNING id", (pond_id, now.date()-timedelta(days=40)))
        active = cur.fetchone()['id']
        cur.execute(f'INSERT INTO {schema}.devices (serial, pond_id) VALUES (%s,%s) RETURNING id', (serial, pond_id))
        device_id = cur.fetchone()['id']
        cur.execute(f'INSERT INTO {schema}.probe_readings (device_serial, device_id, pond_id, cycle_id, recorded_at, alerts_evaluated_at) VALUES (%s,%s,%s,%s,%s,now()) RETURNING id', (serial, device_id, pond_id, active, now-timedelta(days=51)))
        previous_id = cur.fetchone()['id']
    apply_migration(conn, schema, '008_probe_sample_cycles.sql')
    apply_migration(conn, schema, '008_probe_sample_cycles.sql')
    with conn.cursor() as cur:
        cur.execute(f'SELECT cycle_id, alerts_evaluated_at FROM {schema}.probe_readings WHERE id=%s', (previous_id,))
        row = cur.fetchone()
        assert row['cycle_id'] == old_cycle and row['alerts_evaluated_at'] is None
        for sampled_at, expected in ((now-timedelta(days=50), old_cycle), (now, active), (now-timedelta(days=100), None)):
            cur.execute(f'SELECT {schema}.ingest_probe_reading(p_device_serial := %s, p_recorded_at := %s, p_ph := 8) AS id', (serial, sampled_at))
            row_id = cur.fetchone()['id']
            cur.execute(f'SELECT cycle_id FROM {schema}.probe_readings WHERE id=%s', (row_id,))
            assert cur.fetchone()['cycle_id'] == expected
        # A later cycle owns a day that also falls inside an earlier cycle's inclusive end.
        cur.execute(f'UPDATE {schema}.cycles SET harvested_at=%s WHERE id=%s', (now.date(), old_cycle))
        cur.execute(f'SELECT {schema}.cycle_for_sample(%s,%s) AS id', (pond_id, now))
        assert cur.fetchone()['id'] == active
        # With missing dates, only a sole active cycle and a sample from today qualify.
        cur.execute(f'DELETE FROM {schema}.cycles WHERE id=%s', (old_cycle,))
        cur.execute(f'UPDATE {schema}.cycles SET stocked_at=NULL WHERE id=%s', (active,))
        for sampled_at, expected in ((now, active), (now-timedelta(days=2), None)):
            cur.execute(f'SELECT {schema}.cycle_for_sample(%s,%s) AS id', (pond_id, sampled_at))
            assert cur.fetchone()['id'] == expected
