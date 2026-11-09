"""Real transaction locks on a disposable local PostgreSQL, never the .env DB.

Install backend/tests/requirements.txt to run these tests.
"""
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

import alerts
from models import AlertRuleUpdate, CycleUpdate
from routers import ponds
from routers.alerts import update_rule
from test_review_fixes import CYCLE, POND, RULE, init_alert_schema, seed_alert_context

pgserver = pytest.importorskip('pgserver', reason='Install backend/tests/requirements.txt for lock tests')


@pytest.fixture(scope='module')
def local_server():
    with TemporaryDirectory(prefix='shrimp-lock-tests-') as directory:
        server = pgserver.get_server(directory, cleanup_mode='delete')
        try:
            yield server.get_uri()
        finally:
            server.cleanup()


@pytest.fixture
def connections(local_server):
    # Only connect to the URI returned by our newly created local server.
    conns = [psycopg2.connect(local_server, cursor_factory=RealDictCursor,
                            options='-c statement_timeout=10000') for _ in range(3)]
    writer, manager, observer = conns
    observer.autocommit = True
    try:
        with observer.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS shrimp CASCADE')
        init_alert_schema(writer)
        seed_alert_context(writer)
        writer.commit()
        yield writer, manager, observer
    finally:
        for conn in conns:
            alerts._notification_queues.pop(conn, None)
            conn.close()


class DeferredCommit:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)

    def commit(self):
        pass


def manage(conn, action):
    if action == 'disable':
        update_rule(UUID(RULE), AlertRuleUpdate(is_active=False), {}, conn)
    else:
        with patch.object(ponds, 'get_pond_or_404', return_value={'id': POND}), patch.object(ponds, 'require_pond_access'):
            ponds.update_cycle(UUID(CYCLE), CycleUpdate(status=action), {}, conn)


def write_alert(conn):
    # Snapshot taken by an evaluation before the concurrent lifecycle change.
    alerts.upsert_alert(conn, {'id': POND}, {'id': CYCLE, 'status': 'active'},
                        {'code': 'TEST_RULE', 'metric': 'nh3_ppm', 'severity': 'warn'},
                        2, 'test', 'test')


def wait_until_blocked(observer, conn, future):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if future.done():
            future.result()  # Surface SQL errors rather than hiding them.
            pytest.fail('Transaction completed without waiting for the lifecycle lock')
        with observer.cursor() as cur:
            cur.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', (conn.get_backend_pid(),))
            if cur.fetchone()['wait_event_type'] == 'Lock':
                return
        sleep(0.01)
    pytest.fail('Transaction did not reach the expected lock wait')


@pytest.mark.parametrize('action', ['disable', 'harvested', 'aborted'])
@pytest.mark.parametrize('writer_first', [False, True])
def test_lifecycle_change_serializes_with_alert_write(connections, action, writer_first):
    writer, manager, observer = connections
    if writer_first:
        write_alert(writer)
        first, second = writer, manager
        operation = lambda: manage(manager, action)
    else:
        manage(DeferredCommit(manager), action)
        first, second = manager, writer
        operation = lambda: (write_alert(writer), writer.commit())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation)
        try:
            wait_until_blocked(observer, second, future)
        finally:
            first.commit()
        future.result(timeout=10)
    with observer.cursor() as cur:
        cur.execute('SELECT count(*) AS count FROM shrimp.alert_events WHERE resolved_at IS NULL')
        assert cur.fetchone()['count'] == 0
    with patch.object(alerts, 'notify_alert') as notify:
        alerts.flush_notifications(writer)
        alerts.retry_unnotified(writer)
    notify.assert_not_called()


def test_regular_cycle_edit_does_not_wait_for_evaluator(connections):
    writer, manager, _ = connections
    assert alerts.load_active_cycle(writer, POND)['id'] == CYCLE
    with patch.object(ponds, 'get_pond_or_404', return_value={'id': POND}), patch.object(ponds, 'require_pond_access'), patch.object(ponds, 'reevaluate_latest_mineral_tests'):
        result = ponds.update_cycle(UUID(CYCLE), CycleUpdate(stage='nursery'), {}, manager)
    assert result['stage'] == 'nursery'


@pytest.mark.parametrize('action', ['harvested', 'aborted'])
def test_cycle_close_waits_before_non_firing_evaluation_writes(connections, action):
    writer, manager, observer = connections
    alerts.load_active_cycle(writer, POND)
    alerts.resolve_alert(writer, POND, 'TEST_RULE')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(manage, manager, action)
        try:
            wait_until_blocked(observer, manager, future)
        finally:
            writer.commit()
        future.result(timeout=10)


def test_rule_disable_does_not_deadlock_resolve_then_upsert(connections):
    writer, manager, observer = connections
    write_alert(writer)
    writer.commit()
    alerts.resolve_alert(writer, POND, 'TEST_RULE')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(manage, manager, 'disable')
        try:
            wait_until_blocked(observer, manager, future)
            # Another reading in the same worker batch fires the rule again.
            write_alert(writer)
        finally:
            writer.commit()
        future.result(timeout=10)
    with observer.cursor() as cur:
        cur.execute('SELECT count(*) AS count FROM shrimp.alert_events WHERE resolved_at IS NULL')
        assert cur.fetchone()['count'] == 0
