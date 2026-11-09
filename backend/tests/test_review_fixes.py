from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import UUID

import psycopg2
import pytest
from fastapi import HTTPException

import alerts
from embedded_postgres import EmbeddedPostgres
from models import AlertRuleUpdate, CycleUpdate, LoginRequest
from routers import auth_routes, ponds
from routers.alerts import update_rule

POND, CYCLE, OTHER, RULE, EVENT, OTHER_EVENT, PROBE_EVENT = [str(UUID(int=i)) for i in range(1, 8)]


def query(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(psycopg2, 'connect', lambda *a, **k: pytest.fail('external database forbidden'))
    conn = EmbeddedPostgres()
    try:
        init_alert_schema(conn)
        yield conn
    finally:
        conn.close()


def init_alert_schema(conn):
    for sql in (
        'CREATE SCHEMA shrimp',
        'CREATE TABLE shrimp.cycles (id uuid PRIMARY KEY, pond_id uuid, status text, stage text, stocked_at date, harvested_at date, updated_at timestamptz)',
        'CREATE TABLE shrimp.alert_rules (id uuid PRIMARY KEY, code text UNIQUE, min_value numeric, max_value numeric, is_active boolean, updated_at timestamptz)',
        'CREATE TABLE shrimp.alert_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), pond_id uuid, cycle_id uuid, rule_code text, metric text, severity text, value numeric, message_vi text, message_zh text, resolved_at timestamptz, last_notified_at timestamptz, opened_at timestamptz DEFAULT now())',
    ):
        with conn.cursor() as cur:
            cur.execute(sql)


def test_login_blocks_before_password_check_and_expires(monkeypatch):
    username = 'review-limit-test'
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(auth_routes, '_login_failures', {username: [now] * 8})
    conn = MagicMock()
    with patch.object(auth_routes, 'verify_password') as verify:
        with pytest.raises(HTTPException) as error:
            auth_routes.login(LoginRequest(username=username.upper(), password='correct'), conn)
        assert error.value.status_code == 429
        verify.assert_not_called()
        conn.cursor.assert_not_called()
    auth_routes._login_failures[username] = [now - timedelta(minutes=16)] * 8
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as error:
        auth_routes.login(LoginRequest(username=username, password='incorrect'), conn)
    assert error.value.status_code == 401
    assert len(auth_routes._login_failures[username]) == 1


def test_parallel_login_attempts_cannot_both_pass_last_slot(monkeypatch):
    username = 'parallel-limit-test'
    monkeypatch.setattr(auth_routes, '_login_failures', {username: [datetime.now(timezone.utc)] * 7})
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {'password_hash': 'hash'}
    entered, release = Event(), Event()

    def verify(*args):
        entered.set()
        assert release.wait(5)
        return False

    def attempt():
        try:
            auth_routes.login(LoginRequest(username=username, password='wrong'), conn)
        except HTTPException as exc:
            return exc.status_code

    with patch.object(auth_routes, 'verify_password', side_effect=verify) as check:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(attempt)
            assert entered.wait(5)
            second = pool.submit(attempt)
            release.set()
            assert sorted([first.result(), second.result()]) == [401, 429]
        assert check.call_count == 1


@pytest.mark.parametrize('status', ['harvested', 'aborted'])
def test_closing_cycle_resolves_lab_alerts_only(engine, status):
    query(engine, "INSERT INTO shrimp.cycles (id, pond_id, status, stage) VALUES (%s, %s, 'active', 'growout')", (CYCLE, POND))
    for ident, cycle, metric in [(EVENT, CYCLE, 'nh3_ppm'), (OTHER_EVENT, OTHER, 'nh3_ppm'), (PROBE_EVENT, CYCLE, 'ph')]:
        query(engine, "INSERT INTO shrimp.alert_events (id, pond_id, cycle_id, rule_code, metric) VALUES (%s, %s, %s, 'RULE', %s)", (ident, POND, cycle, metric))
    with patch.object(ponds, 'get_pond_or_404', return_value={'id': POND}), patch.object(ponds, 'require_pond_access'):
        ponds.update_cycle(UUID(CYCLE), CycleUpdate(status=status), {}, engine)
    rows = {r['id']: r['resolved_at'] for r in query(engine, 'SELECT id, resolved_at FROM shrimp.alert_events')}
    assert rows[EVENT] is not None
    assert rows[OTHER_EVENT] is None and rows[PROBE_EVENT] is None


def test_disabled_rule_resolves_alerts_and_skips_queued_and_retry(engine):
    query(engine, "INSERT INTO shrimp.alert_rules (id, code, max_value, is_active) VALUES (%s, 'NH3_DANGER', 0.1, true), (%s, 'PH_HIGH', 8, true)", (RULE, OTHER))
    query(engine, "INSERT INTO shrimp.alert_events (id, pond_id, rule_code, metric) VALUES (%s, %s, 'NH3_DANGER', 'nh3_ppm'), (%s, %s, 'PH_HIGH', 'ph')", (EVENT, POND, OTHER_EVENT, POND))
    alerts._queue_notification(engine, {'id': EVENT}, {'id': POND})
    update_rule(UUID(RULE), AlertRuleUpdate(is_active=False), {}, engine)
    rows = {r['id']: r['resolved_at'] for r in query(engine, 'SELECT id, resolved_at FROM shrimp.alert_events')}
    assert rows[EVENT] is not None and rows[OTHER_EVENT] is None
    query(engine, "INSERT INTO shrimp.alert_events (id, pond_id, rule_code, metric) VALUES (%s, %s, 'NH3_DANGER', 'nh3_ppm')", (PROBE_EVENT, POND))
    with patch.object(alerts, 'notify_alert') as notify, patch.object(alerts, 'load_pond', return_value={'id': POND}):
        alerts.flush_notifications(engine)
        notify.assert_not_called()
        alerts.retry_unnotified(engine)
        assert [call.args[1]['id'] for call in notify.call_args_list] == [OTHER_EVENT]


def test_editing_stocking_date_cannot_pass_existing_harvest_date():
    from datetime import date
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {
        'id': CYCLE, 'pond_id': POND, 'status': 'harvested',
        'stocked_at': date(2026, 1, 1), 'harvested_at': date(2026, 2, 1),
    }
    with patch.object(ponds, 'get_pond_or_404', return_value={'id': POND}), patch.object(ponds, 'require_pond_access'):
        with pytest.raises(HTTPException) as error:
            ponds.update_cycle(UUID(CYCLE), CycleUpdate(stocked_at=date(2026, 2, 2)), {}, conn)
    assert error.value.status_code == 422
    conn.commit.assert_not_called()


def seed_alert_context(engine, metric='nh3_ppm'):
    query(engine, "INSERT INTO shrimp.cycles (id, pond_id, status, stage) VALUES (%s, %s, 'active', 'growout') RETURNING id", (CYCLE, POND))
    query(engine, "INSERT INTO shrimp.alert_rules (id, code, max_value, is_active) VALUES (%s, 'TEST_RULE', 1, true) RETURNING id", (RULE,))
    return {'id': POND}, {'id': CYCLE, 'status': 'active'}, {'code': 'TEST_RULE', 'metric': metric, 'severity': 'warn'}


def close_cycle(engine, status):
    with patch.object(ponds, 'get_pond_or_404', return_value={'id': POND}), patch.object(ponds, 'require_pond_access'):
        ponds.update_cycle(UUID(CYCLE), CycleUpdate(status=status), {}, engine)


@pytest.mark.parametrize('write_first', [False, True])
def test_disable_rule_and_stale_evaluation_in_either_order(engine, write_first):
    pond, cycle, rule = seed_alert_context(engine)
    if write_first:
        alerts.upsert_alert(engine, pond, cycle, rule, 2, 'test', 'test')
    update_rule(UUID(RULE), AlertRuleUpdate(is_active=False), {}, engine)
    if not write_first:
        # Resume an evaluator that read the rule before it was disabled.
        alerts.upsert_alert(engine, pond, cycle, rule, 2, 'test', 'test')
    assert not query(engine, 'SELECT id FROM shrimp.alert_events WHERE resolved_at IS NULL')
    with patch.object(alerts, 'notify_alert') as notify:
        alerts.flush_notifications(engine)
        alerts.retry_unnotified(engine)
    notify.assert_not_called()


@pytest.mark.parametrize('status', ['harvested', 'aborted'])
@pytest.mark.parametrize('write_first', [False, True])
def test_close_cycle_and_stale_evaluation_in_either_order(engine, status, write_first):
    pond, cycle, rule = seed_alert_context(engine)
    if write_first:
        alerts.upsert_alert(engine, pond, cycle, rule, 2, 'test', 'test')
    close_cycle(engine, status)
    if not write_first:
        # Resume an evaluator that read the active cycle before it ended.
        alerts.upsert_alert(engine, pond, cycle, rule, 2, 'test', 'test')
    assert not query(engine, 'SELECT id FROM shrimp.alert_events WHERE resolved_at IS NULL')
    with patch.object(alerts, 'notify_alert') as notify:
        alerts.flush_notifications(engine)
        alerts.retry_unnotified(engine)
    notify.assert_not_called()


@pytest.mark.parametrize('metric', ['ph', 'do_mg_l', 'heartbeat'])
def test_pond_monitoring_continues_after_cycle_ends(engine, metric):
    pond, cycle, rule = seed_alert_context(engine, metric)
    close_cycle(engine, 'aborted')
    alerts.upsert_alert(engine, pond, cycle, rule, 2, 'test', 'test')
    assert len(query(engine, 'SELECT id FROM shrimp.alert_events WHERE resolved_at IS NULL')) == 1
    with patch.object(alerts, 'notify_alert') as notify:
        alerts.flush_notifications(engine)
    notify.assert_called_once()


def test_closed_cycle_legacy_alert_is_not_queued_or_retried(engine):
    pond, cycle, rule = seed_alert_context(engine)
    close_cycle(engine, 'aborted')
    query(engine, "INSERT INTO shrimp.alert_events (id, pond_id, cycle_id, rule_code, metric) VALUES (%s, %s, %s, 'TEST_RULE', 'nh3_ppm')", (EVENT, POND, CYCLE))
    alerts._queue_notification(engine, {'id': EVENT}, pond)
    with patch.object(alerts, 'notify_alert') as notify, patch.object(alerts, 'load_pond', return_value=pond):
        alerts.flush_notifications(engine)
        alerts.retry_unnotified(engine)
    notify.assert_not_called()
