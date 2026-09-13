import asyncio
import os
import runpy
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import alerts
import auth
import main
from models import AlertRuleUpdate
from routers.alerts import update_rule


def connection_with_cursor():
    conn = MagicMock()
    return conn, conn.cursor.return_value.__enter__.return_value


def test_mixed_fresh_and_stale_devices_keep_alert_open():
    conn, cur = connection_with_cursor()
    cur.fetchall.side_effect = [
        [{"pond_id": "pond-a"}, {"pond_id": "pond-a"}],
        [{"pond_id": "pond-a"}, {"pond_id": "pond-b"}],
    ]
    rule = {"code": "DEVICE_STALE", "max_value": 60}
    with patch.object(alerts, "load_rules", return_value={"DEVICE_STALE": rule}), \
         patch.object(alerts, "load_pond", return_value={"id": "pond-a"}), \
         patch.object(alerts, "load_active_cycle", return_value=None), \
         patch.object(alerts, "resolve_alert") as resolve, \
         patch.object(alerts, "upsert_alert") as upsert:
        alerts.evaluate_stale_devices(conn)
    resolve.assert_called_once_with(conn, "pond-b", "DEVICE_STALE")
    upsert.assert_called_once()


def test_probe_reading_does_not_clear_other_devices_outage():
    conn, _ = connection_with_cursor()
    with patch.object(alerts, "load_pond", return_value={"id": "pond-a"}), \
         patch.object(alerts, "load_active_cycle", return_value=None), \
         patch.object(alerts, "load_rules", return_value={}), \
         patch.object(alerts, "resolve_alert") as resolve:
        alerts.evaluate_probe_reading(conn, {"id": 1, "pond_id": "pond-a"})
    resolve.assert_not_called()


@pytest.mark.parametrize("code,field", [("PH_HIGH", "max_value"), ("DO_LOW", "min_value")])
def test_rule_required_threshold_cannot_be_cleared(code, field):
    conn, cur = connection_with_cursor()
    cur.fetchone.return_value = {"code": code, "min_value": 4, "max_value": 8, "is_active": True}
    with pytest.raises(HTTPException) as error:
        update_rule(uuid4(), AlertRuleUpdate(**{field: None}), {}, conn)
    assert error.value.status_code == 422
    conn.commit.assert_not_called()


def test_worker_keeps_event_loop_responsive():
    async def scenario():
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        conn, _ = connection_with_cursor()

        def slow_processing(_conn):
            started.set()
            release.wait(timeout=0.5)

        with patch.object(main, "get_connection", return_value=conn), \
             patch.object(main, "process_pending_readings", side_effect=slow_processing), \
             patch.object(main, "evaluate_stale_devices"), \
             patch.object(main, "_handle_telegram_updates", side_effect=finished.set):
            loop = asyncio.get_running_loop()
            before = loop.time()
            worker = asyncio.create_task(main._worker())
            try:
                while not started.is_set():
                    await asyncio.sleep(0.005)
                assert loop.time() - before < 0.25
            finally:
                release.set()
                while not finished.is_set():
                    await asyncio.sleep(0.005)
                worker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await worker

    asyncio.run(scenario())


def test_existing_alert_refreshes_values_before_notification():
    conn, cur = connection_with_cursor()
    previous = {"id": "event-a", "value": 8, "last_notified_at": None}
    updated = previous | {"value": 9, "message_zh": "updated", "severity": "critical"}
    cur.fetchone.side_effect = [previous, updated]
    rule = {"code": "PH_HIGH", "severity": "critical", "metric": "ph"}
    pond = {"id": "pond-a"}
    with patch.object(alerts, "notify_alert") as notify:
        alerts.upsert_alert(conn, pond, None, rule, 9, "updated", "updated")
    notify.assert_called_once_with(conn, updated, pond)


@pytest.mark.parametrize("code,threshold", [("PH_HIGH", 8.2), ("ALK_LOW", 140), ("DEVICE_STALE", 30)])
def test_alert_messages_use_configured_threshold(code, threshold):
    vi, zh = alerts._msg(code, 0, threshold=threshold)
    assert str(threshold) in vi
    assert str(threshold) in zh


def test_harvest_rule_is_independent_of_no2_warning():
    conn, _ = connection_with_cursor()
    rule = {"code": "NO2_HARVEST_EARLY", "max_value": 9}
    with patch.object(alerts, "load_pond", return_value={"id": "pond-a", "pond_type": "growout"}), \
         patch.object(alerts, "load_active_cycle", return_value=None), \
         patch.object(alerts, "load_lookup", return_value=[]), \
         patch.object(alerts, "_latest_ph", return_value=None), \
         patch.object(alerts, "load_rules", return_value={rule["code"]: rule}), \
         patch.object(alerts, "consecutive_no2_days", return_value=7) as streak, \
         patch.object(alerts, "upsert_alert") as upsert:
        alerts.evaluate_lab_test(conn, {"pond_id": "pond-a", "no2_ppm": 10})
    streak.assert_called_once_with(conn, "pond-a", 9)
    upsert.assert_called_once()


def test_invalid_token_subject_returns_401_without_querying_db():
    conn, _ = connection_with_cursor()
    credentials = MagicMock(credentials="token")
    with patch.object(auth, "decode_token", return_value={"sub": "not-a-uuid"}), \
         pytest.raises(HTTPException) as error:
        auth.get_current_user(credentials, conn)
    assert error.value.status_code == 401
    conn.cursor.assert_not_called()


def test_valid_rule_update_commits():
    conn, cur = connection_with_cursor()
    rule_id = uuid4()
    existing = {"id": rule_id, "code": "PH_HIGH", "max_value": 7.8}
    cur.fetchone.side_effect = [existing, existing | {"max_value": 8.2}]
    result = update_rule(rule_id, AlertRuleUpdate(max_value=8.2), {}, conn)
    assert result["max_value"] == 8.2
    conn.commit.assert_called_once()


@pytest.mark.parametrize("secret", ["", "fallback-secret"])
def test_missing_or_public_signing_key_prevents_startup(secret):
    result = subprocess.run(
        [sys.executable, "-c", "import auth"],
        cwd=Path(main.__file__).parent,
        env=os.environ | {"JWT_SECRET": secret},
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "JWT_SECRET must be configured" in result.stderr


def test_init_database_requires_explicit_connection_settings():
    script = Path(main.__file__).parents[1] / "scripts" / "init_db.py"
    with patch.dict(os.environ, {"ADMIN_DATABASE_URL": ""}), \
         patch("psycopg2.connect") as connect:
        namespace = runpy.run_path(str(script))
        with pytest.raises(SystemExit) as error:
            namespace["main"]()
    assert error.value.code == 1
    connect.assert_not_called()
