"""Sensor integration checks use unique rows in a transaction that is rolled back."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor
from fastapi.testclient import TestClient

from auth import get_current_user
from db import DATABASE_URL, get_db
from main import app
from routers.dashboard import dashboard
from routers.ponds import get_pond, pond_readings


@pytest.fixture
def sensor_device():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL missing")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    token = uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shrimp.users (username, email, password_hash, role, display_name)
                VALUES (%s, %s, 'unused', 'farmer', 'Sensor test') RETURNING id
                """,
                (f"__sensor_{token}", f"{token}@example.com"),
            )
            farmer_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO shrimp.ponds (farmer_id, code, name)
                VALUES (%s, %s, 'Sensor test') RETURNING id
                """,
                (farmer_id, f"__sensor_{token}"),
            )
            pond_id = cur.fetchone()["id"]
            serial = token[:12].upper()
            cur.execute(
                "INSERT INTO shrimp.devices (serial, pond_id) VALUES (%s, %s)",
                (serial, pond_id),
            )
        yield conn, serial, pond_id
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("do_temp", [Decimal("26.08"), None, Decimal("0")])
def test_full_sensor_ingest_and_api_use_only_do_temperature(sensor_device, do_temp):
    conn, serial, pond_id = sensor_device
    recorded_at = datetime.now(timezone.utc)
    raw = {"ip": "192.168.105.164", "rssi_dbm": -56, "hostname": "shrimp-235164.local"}
    expected = {
        "ph": Decimal("8.74"), "ph_mv": Decimal("-50.4"),
        "ph_temp_c": Decimal("25.23"), "conductivity_us_cm": Decimal("26.0"),
        "salinity_ppt": Decimal("15.84"), "cond_temp_c": Decimal("26.41"),
        "tds_mg_l": Decimal("16613.7"), "do_mg_l": Decimal("5.62"),
        "do_sat_pct": Decimal("0.7"), "do_temp_c": do_temp, "temp_c": do_temp,
    }
    query = """
        SELECT shrimp.ingest_probe_reading(
            p_device_serial := %s, p_recorded_at := %s,
            p_ph := 8.74, p_ph_mv := -50.4, p_ph_temp_c := 25.23,
            p_conductivity_us_cm := 26.0, p_salinity_ppt := 15.84,
            p_cond_temp_c := 26.41, p_tds_mg_l := 16613.7,
            p_do_mg_l := 5.62, p_do_sat_pct := 0.7, p_do_temp_c := %s,
            p_raw := %s
        ) AS id
    """
    with conn.cursor() as cur:
        cur.execute(query, (serial, recorded_at, do_temp, Json(raw)))
        reading_id = cur.fetchone()["id"]
        cur.execute(query, (serial, recorded_at, do_temp, Json(raw)))
        assert cur.fetchone()["id"] == reading_id
        cur.execute("SELECT * FROM shrimp.probe_readings WHERE id = %s", (reading_id,))
        row = cur.fetchone()
        assert {key: row[key] for key in expected} == expected
        assert row["raw"] == raw

    user = {"role": "admin"}
    detail = get_pond(pond_id, user, conn)["latest_reading"]
    assert detail["raw"] == raw
    history = pond_readings(pond_id, "24h", user, conn)
    assert len(history) == 1
    for result in (detail, history[0]):
        assert {
            key: Decimal(str(result[key])) if result[key] is not None else None
            for key in expected
        } == expected
    summary = next(p for p in dashboard(user, conn)["ponds"] if p["id"] == str(pond_id))
    for key in expected.keys() - {"do_temp_c"}:
        assert (Decimal(str(summary[key])) if summary[key] is not None else None) == expected[key]

    # The derived value follows DO temperature changes; other probe temperatures stay intact.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shrimp.probe_readings SET do_temp_c = 27.12 WHERE id = %s RETURNING temp_c, ph_temp_c, cond_temp_c",
            (reading_id,),
        )
        assert dict(cur.fetchone()) == {
            "temp_c": Decimal("27.12"), "ph_temp_c": Decimal("25.23"),
            "cond_temp_c": Decimal("26.41"),
        }


def test_http_ingestion_key_rotation_and_device_binding(sensor_device):
    conn, serial, pond_id = sensor_device
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM shrimp.devices WHERE mac_address = %s", (serial,))
        device_id = cur.fetchone()["id"]
        cur.execute("SAVEPOINT http_request")

    class TransactionConnection:
        """Simulate request commits with savepoints; the outer fixture rolls everything back."""
        def cursor(self, *args, **kwargs):
            return conn.cursor(*args, **kwargs)

        def commit(self):
            with conn.cursor() as cur:
                cur.execute("RELEASE SAVEPOINT http_request")
                cur.execute("SAVEPOINT http_request")

        def rollback(self):
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT http_request")
            self.commit()

    request_conn = TransactionConnection()
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: request_conn
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    client = TestClient(app)
    body = {
        "device_serial": serial.lower(), "recorded_at": datetime.now(timezone.utc).isoformat(),
        "ph": 8.74, "ph_temp_c": 25.23, "cond_temp_c": 26.41,
        "do_mg_l": 5.62, "do_sat_pct": 0.7, "do_temp_c": 26.08,
    }
    try:
        issued = client.post(f"/api/devices/{device_id}/ingest-key")
        assert issued.status_code == 200
        key = issued.json()["api_key"]
        headers = {"X-Device-Key": key}
        response = client.post("/api/probe-readings", json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["temp_c"] == 26.08
        repeated = client.post("/api/probe-readings", json=body | {"do_temp_c": 0}, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json() == response.json()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM shrimp.probe_readings WHERE device_serial = %s", (serial,))
            assert cur.fetchone()["n"] == 1
            cur.execute("SELECT key_hash FROM shrimp.device_api_keys WHERE device_id = %s", (device_id,))
            assert cur.fetchone()["key_hash"] != key

        wrong_mac = client.post("/api/probe-readings", json=body | {"device_serial": "000000000000"}, headers=headers)
        assert wrong_mac.status_code == 401
        rotated = client.post(f"/api/devices/{device_id}/ingest-key")
        assert rotated.status_code == 200
        assert client.post("/api/probe-readings", json=body, headers=headers).status_code == 401
        headers = {"X-Device-Key": rotated.json()["api_key"]}
        assert client.post("/api/probe-readings", json=body, headers=headers).status_code == 200

        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.devices SET is_active = false WHERE id = %s", (device_id,))
        request_conn.commit()
        assert client.post("/api/probe-readings", json=body, headers=headers).status_code == 401
        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.devices SET is_active = true, pond_id = NULL WHERE id = %s", (device_id,))
        request_conn.commit()
        assert client.post("/api/probe-readings", json=body, headers=headers).status_code == 409

        # Installation codes replace factory-time key provisioning.
        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.devices SET pond_id = %s WHERE id = %s", (pond_id, device_id))
        request_conn.commit()
        first_code = client.post(f"/api/devices/{device_id}/activation-code")
        assert first_code.status_code == 200
        code1 = first_code.json()["activation_code"]
        with conn.cursor() as cur:
            cur.execute("SELECT code_hash FROM shrimp.device_activation_codes WHERE device_id = %s", (device_id,))
            assert cur.fetchone()["code_hash"] != code1
        code2 = client.post(f"/api/devices/{device_id}/activation-code").json()["activation_code"]
        activation = {"device_serial": serial.lower(), "activation_code": code1}
        assert client.post("/api/devices/activate", json=activation).status_code == 401
        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.device_activation_codes SET expires_at = now() - interval '1 second' WHERE device_id = %s", (device_id,))
        request_conn.commit()
        assert client.post("/api/devices/activate", json=activation | {"activation_code": code2}).status_code == 401

        code3 = client.post(f"/api/devices/{device_id}/activation-code").json()["activation_code"]
        activation["activation_code"] = code3
        assert client.post("/api/devices/activate", json=activation | {"device_serial": "000000000000"}).status_code == 401
        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.devices SET is_active = false WHERE id = %s", (device_id,))
        request_conn.commit()
        assert client.post("/api/devices/activate", json=activation).status_code == 409
        with conn.cursor() as cur:
            cur.execute("UPDATE shrimp.devices SET is_active = true WHERE id = %s", (device_id,))
        request_conn.commit()
        activated = client.post("/api/devices/activate", json=activation)
        assert activated.status_code == 200
        assert activated.headers["cache-control"] == "no-store"
        activated_key = activated.json()["api_key"]
        assert client.post("/api/devices/activate", json=activation).status_code == 401
        assert client.post("/api/probe-readings", json=body, headers=headers).status_code == 401
        assert client.post("/api/probe-readings", json=body, headers={"X-Device-Key": activated_key}).status_code == 200

        pending = client.post(f"/api/devices/{device_id}/activation-code").json()["activation_code"]
        assert client.post(f"/api/devices/{device_id}/ingest-key").status_code == 200
        assert client.post("/api/devices/activate", json=activation | {"activation_code": pending}).status_code == 401
    finally:
        client.close()
        app.dependency_overrides = overrides
