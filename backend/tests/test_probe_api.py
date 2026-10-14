from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auth import get_current_user
from db import get_db
from main import app
from models import ProbeReadingCreate
from routers.probe_readings import key_hash


@pytest.fixture
def api_client():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    try:
        yield TestClient(app), conn, cur
    finally:
        app.dependency_overrides = overrides


def payload():
    return {
        "device_serial": "84:0d:8e:23:51:64", "recorded_at": "2026-10-13T17:30:00+07:00",
        "ph": 8.74, "ph_mv": -50.4, "ph_temp_c": 25.23,
        "conductivity_us_cm": 26.0, "salinity_ppt": 15.84,
        "cond_temp_c": 26.41, "tds_mg_l": 16613.7,
        "do_mg_l": 5.62, "do_sat_pct": 0.7, "do_temp_c": 26.08,
        "raw": {"ip": "192.168.105.164", "rssi_dbm": -56},
    }


def test_ingest_requires_key_before_opening_database(api_client):
    client, conn, _ = api_client
    assert client.post("/api/probe-readings", json=payload()).status_code == 401
    conn.cursor.assert_not_called()


def test_invalid_key_or_mac_cannot_ingest(api_client):
    client, conn, cur = api_client
    cur.fetchone.return_value = None
    response = client.post("/api/probe-readings", json=payload(), headers={"X-Device-Key": "wrong"})
    assert response.status_code == 401
    assert cur.execute.call_count == 1
    assert cur.execute.call_args.args[1] == (key_hash("wrong"), "840D8E235164")
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


def test_success_commits_and_returns_stored_receipt(api_client):
    client, conn, cur = api_client
    receipt = {"id": 42, "device_serial": "840D8E235164", "recorded_at": datetime.now(timezone.utc), "temp_c": 26.08}
    cur.fetchone.side_effect = [{"id": str(uuid4())}, {"id": 42}, receipt]
    response = client.post("/api/probe-readings", json=payload(), headers={"X-Device-Key": "secret"})
    assert response.status_code == 200
    assert response.json()["id"] == 42
    assert response.json()["temp_c"] == 26.08
    args = cur.execute.call_args_list[1].args[1]
    assert args[0] == "840D8E235164"
    assert args[2:12] == (8.74, -50.4, 25.23, 26.0, 15.84, 26.41, 16613.7, 5.62, 0.7, 26.08)
    assert args[12].adapted == payload()["raw"]
    conn.commit.assert_called_once()


@pytest.mark.parametrize("changes", [
    {"recorded_at": "2026-10-13T17:30:00"}, {"device_serial": "invalid"},
    {"ph": 15}, {"do_mg_l": -1}, {"temp_c": 25}, {"pond_id": str(uuid4())},
])
def test_invalid_payload_does_not_write(api_client, changes):
    client, conn, cur = api_client
    response = client.post("/api/probe-readings", json=payload() | changes, headers={"X-Device-Key": "secret"})
    assert response.status_code == 422
    cur.execute.assert_not_called()
    conn.commit.assert_not_called()


def test_far_future_reading_is_rejected_before_database_write(api_client):
    client, conn, cur = api_client
    future = datetime.now(timezone.utc) + timedelta(minutes=6)
    response = client.post(
        "/api/probe-readings",
        json=payload() | {"recorded_at": future.isoformat()},
        headers={"X-Device-Key": "secret"},
    )
    assert response.status_code == 422
    cur.execute.assert_not_called()
    conn.commit.assert_not_called()


@pytest.mark.parametrize("field", ["ph", "ph_mv", "do_temp_c", "do_sat_pct", "tds_mg_l"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_sensor_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ProbeReadingCreate(**(payload() | {field: value}))


@pytest.mark.parametrize("code,status", [("22023", 409), ("22003", 422), ("08006", 503)])
def test_database_error_rolls_back_and_hides_details(api_client, code, status):
    class DatabaseError(psycopg2.Error):
        @property
        def pgcode(self):
            return code

    client, conn, cur = api_client
    cur.fetchone.return_value = {"id": str(uuid4())}
    cur.execute.side_effect = [None, DatabaseError("private database detail")]
    response = client.post("/api/probe-readings", json=payload(), headers={"X-Device-Key": "secret"})
    assert response.status_code == status
    assert "private database detail" not in response.text
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_admin_issues_key_and_stores_only_hash(api_client):
    client, conn, cur = api_client
    device_id = uuid4()
    cur.fetchone.return_value = {"mac_address": "840D8E235164"}
    response = client.post(f"/api/devices/{device_id}/ingest-key")
    assert response.status_code == 200
    key = response.json()["api_key"]
    assert len(key) >= 43
    assert cur.execute.call_args_list[-2].args[1] == (str(device_id), key_hash(key))
    assert "DELETE FROM shrimp.device_activation_codes" in cur.execute.call_args.args[0]
    conn.commit.assert_called_once()


def test_only_admin_can_issue_device_keys(api_client):
    client, conn, _ = api_client
    app.dependency_overrides[get_current_user] = lambda: {"role": "farmer"}
    assert client.post(f"/api/devices/{uuid4()}/ingest-key").status_code == 403
    conn.cursor.assert_not_called()


def test_admin_issues_hashed_activation_code_with_expiry(api_client):
    client, conn, cur = api_client
    device_id = uuid4()
    expiry = datetime.now(timezone.utc)
    cur.fetchone.side_effect = [
        {"mac_address": "840D8E235164", "pond_id": str(uuid4()), "is_active": True},
        {"expires_at": expiry},
    ]
    response = client.post(f"/api/devices/{device_id}/activation-code")
    assert response.status_code == 200
    code = response.json()["activation_code"]
    assert len(code) == 32
    assert cur.execute.call_args.args[1] == (str(device_id), key_hash(code))
    assert response.headers["cache-control"] == "no-store"
    conn.commit.assert_called_once()


def test_only_admin_can_issue_activation_codes(api_client):
    client, conn, _ = api_client
    app.dependency_overrides[get_current_user] = lambda: {"role": "salesperson"}
    assert client.post(f"/api/devices/{uuid4()}/activation-code").status_code == 403
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("device", [None,
    {"mac_address": None, "is_active": True, "pond_id": str(uuid4())},
    {"mac_address": "840D8E235164", "is_active": False, "pond_id": str(uuid4())},
    {"mac_address": "840D8E235164", "is_active": True, "pond_id": None},
])
def test_unavailable_device_cannot_receive_code(api_client, device):
    client, conn, cur = api_client
    cur.fetchone.return_value = device
    response = client.post(f"/api/devices/{uuid4()}/activation-code")
    assert response.status_code == (404 if device is None else 409)
    conn.commit.assert_not_called()


def test_activation_returns_device_key_after_committing(api_client):
    client, conn, cur = api_client
    device_id = str(uuid4())
    cur.fetchone.side_effect = [
        {"id": device_id, "mac_address": "840D8E235164", "is_active": True, "pond_id": str(uuid4())},
        {"used_at": None, "valid": True},
    ]
    response = client.post("/api/devices/activate", json={"device_serial": "84:0d:8e:23:51:64", "activation_code": "A" * 32})
    assert response.status_code == 200
    key = response.json()["api_key"]
    assert cur.execute.call_args_list[2].args[1] == (device_id, key_hash(key))
    assert "used_at = clock_timestamp()" in cur.execute.call_args.args[0]
    assert response.headers["cache-control"] == "no-store"
    conn.commit.assert_called_once()


@pytest.mark.parametrize("code", [None, {"used_at": datetime.now(timezone.utc), "valid": True}, {"used_at": None, "valid": False}])
def test_invalid_used_or_expired_code_does_not_replace_key(api_client, code):
    client, conn, cur = api_client
    cur.fetchone.side_effect = [
        {"id": str(uuid4()), "mac_address": "840D8E235164", "is_active": True, "pond_id": str(uuid4())}, code,
    ]
    response = client.post("/api/devices/activate", json={"device_serial": "840D8E235164", "activation_code": "A" * 32})
    assert response.status_code == 401
    assert cur.execute.call_count == 2
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
