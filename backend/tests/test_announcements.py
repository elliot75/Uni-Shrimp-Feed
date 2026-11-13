from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from embedded_postgres import EmbeddedPostgres
from auth import get_current_user
from db import get_db
from main import app
from routers import announcements
import announcement_worker


def ident(i):
    return str(UUID(int=i))


@pytest.fixture
def env(monkeypatch):
    conn = EmbeddedPostgres()
    with conn.cursor() as cur:
        cur.execute('CREATE SCHEMA shrimp')
        cur.execute('CREATE TABLE shrimp.users (id uuid PRIMARY KEY, username text, display_name text, telegram_chat_id text, is_active boolean)')
        for i, chat, active in [(1, 'a', True), (2, 'b', True), (3, 'a', True), (4, None, True), (5, 'c', False), (9, None, True)]:
            cur.execute('INSERT INTO shrimp.users VALUES (%s, %s, %s, %s, %s)', (ident(i), f'user{i}', f'Name {i}', chat, active))
        for statement in (Path(__file__).resolve().parents[1] / 'sql/010_telegram_announcements.sql').read_text().split(';'):
            if statement.strip(): cur.execute(statement)
    monkeypatch.setattr(conn, 'rollback', lambda: None, raising=False)
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_user] = lambda: {'id': ident(9), 'role': 'admin'}
    monkeypatch.setattr(announcements, 'bot_configured', lambda: True)
    sender = Mock(return_value=(True, None))
    monkeypatch.setattr(announcement_worker, 'send_message', sender)
    monkeypatch.setattr(announcement_worker, 'get_connection', lambda: conn)
    original_close = conn.close
    monkeypatch.setattr(conn, 'close', lambda: None)
    yield TestClient(app), conn, sender
    app.dependency_overrides.clear()
    original_close()


def payload(*numbers):
    return {'id': ident(100), 'message': '通知', 'user_ids': [ident(i) for i in numbers]}


def test_durable_job_is_idempotent_and_shared_chat_sent_once(env):
    client, conn, sender = env
    body = payload(1, 2, 3)
    assert client.post('/api/announcements/telegram', json=body).status_code == 202
    assert client.post('/api/announcements/telegram', json=body).status_code == 202
    sender.assert_not_called()
    announcement_worker.process_announcements()
    response = client.get('/api/announcements/telegram/' + body['id'])
    assert [r['status'] for r in response.json()['recipients']] == ['sent'] * 3
    assert sender.call_count == 2
    announcement_worker.process_announcements()
    assert sender.call_count == 2


def test_disabled_or_rebound_after_queuing_is_skipped(env):
    client, conn, sender = env
    body = payload(1, 2)
    assert client.post('/api/announcements/telegram', json=body).status_code == 202
    with conn.cursor() as cur:
        cur.execute('UPDATE shrimp.users SET is_active = false WHERE id = %s', (ident(1),))
        cur.execute("UPDATE shrimp.users SET telegram_chat_id = 'new' WHERE id = %s", (ident(2),))
    announcement_worker.process_announcements()
    assert [r['status'] for r in client.get('/api/announcements/telegram/' + body['id']).json()['recipients']] == ['skipped', 'skipped']
    sender.assert_not_called()


def test_uncertain_delivery_not_retried(env):
    client, conn, sender = env
    body = payload(1)
    client.post('/api/announcements/telegram', json=body)
    sender.return_value = (False, 'timeout')
    announcement_worker.process_announcements()
    announcement_worker.process_announcements()
    assert client.get('/api/announcements/telegram/' + body['id']).json()['recipients'][0]['status'] == 'unknown'
    sender.assert_called_once()


def test_non_admin_and_ineligible_recipient_rejected(env):
    client, conn, sender = env
    assert client.post('/api/announcements/telegram', json=payload(1, 5)).status_code == 409
    app.dependency_overrides[get_current_user] = lambda: {'id': ident(1), 'role': 'farmer'}
    assert client.post('/api/announcements/telegram', json=payload(1)).status_code == 403
    sender.assert_not_called()


def test_interrupted_delivery_becomes_unknown_without_resending(env):
    client, conn, sender = env
    body = payload(1)
    client.post('/api/announcements/telegram', json=body)
    with conn.cursor() as cur:
        cur.execute("UPDATE shrimp.telegram_announcement_chats SET status = 'processing', started_at = now() - interval '3 minutes' WHERE announcement_id = %s", (body['id'],))
        cur.execute("UPDATE shrimp.telegram_announcement_recipients SET status = 'processing' WHERE announcement_id = %s", (body['id'],))
    announcement_worker.process_announcements()
    assert client.get('/api/announcements/telegram/' + body['id']).json()['recipients'][0]['status'] == 'unknown'
    sender.assert_not_called()


def test_more_than_1000_recipients_are_queued(env):
    client, conn, sender = env
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO shrimp.users
                       SELECT (lpad(to_hex(i), 32, '0'))::uuid, 'bulk' || i, 'Bulk', 'shared', true
                       FROM generate_series(1000, 2000) AS i""")
    body = {'id': ident(3000), 'message': '公告', 'user_ids': [ident(i) for i in range(1000, 2001)]}
    response = client.post('/api/announcements/telegram', json=body)
    assert response.status_code == 202
    assert len(response.json()['recipients']) == 1001
    announcement_worker.process_announcements()
    sender.assert_called_once_with('shared', '公告')


def test_reused_job_id_with_different_message_is_rejected(env):
    client, conn, sender = env
    body = payload(1)
    assert client.post('/api/announcements/telegram', json=body).status_code == 202
    assert client.post('/api/announcements/telegram', json={**body, 'message': '另一則'}).status_code == 409
    sender.assert_not_called()
