from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
os.environ["SKIP_WORKER"] = "1"

from main import app  # noqa: E402

DATABASE_URL = os.getenv("DATABASE_URL")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PREFIX = "__test_acc_"


def _admin_conn():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def _cleanup(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM shrimp.salesperson_farmers WHERE salesperson_id IN (SELECT id FROM shrimp.users WHERE username LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.alert_events WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.cycles WHERE pond_id IN (SELECT id FROM shrimp.ponds WHERE code LIKE %s)", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.devices WHERE serial LIKE %s", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.ponds WHERE code LIKE %s", (PREFIX + "%",))
    cur.execute("DELETE FROM shrimp.users WHERE username LIKE %s", (PREFIX + "%",))
    cur.close()


@pytest.fixture
def client():
    if not DATABASE_URL:
        pytest.skip("no db")
    conn = _admin_conn()
    _cleanup(conn)
    cur = conn.cursor()
    users = {
        "admin": ("admin", "zh-TW"),
        "sales": ("salesperson", "vi"),
        "farmer_a": ("farmer", "vi"),
        "farmer_b": ("farmer", "vi"),
    }
    ids = {}
    for name, (role, locale) in users.items():
        cur.execute(
            """
            INSERT INTO shrimp.users (username, email, password_hash, role, display_name, locale)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (PREFIX + name, f"{PREFIX}{name}@ex.com", pwd.hash("password12"), role, name, locale),
        )
        ids[name] = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO shrimp.salesperson_farmers (salesperson_id, farmer_id) VALUES (%s, %s)",
        (ids["sales"], ids["farmer_a"]),
    )
    cur.execute(
        """
        INSERT INTO shrimp.ponds (farmer_id, code, name, pond_type)
        VALUES (%s, %s, 'A', 'growout'), (%s, %s, 'B', 'growout')
        """,
        (ids["farmer_a"], PREFIX + "A", ids["farmer_b"], PREFIX + "B"),
    )
    cur.close()
    with TestClient(app) as c:
        yield c, ids
    _cleanup(conn)
    conn.close()


def login(client, name):
    res = client.post("/api/auth/login", json={"username": PREFIX + name, "password": "password12"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_disabled_user_cannot_login(client):
    c, ids = client
    conn = _admin_conn()
    cur = conn.cursor()
    cur.execute("UPDATE shrimp.users SET is_active = false WHERE id = %s", (ids["farmer_a"],))
    cur.close()
    conn.close()
    res = c.post("/api/auth/login", json={"username": PREFIX + "farmer_a", "password": "password12"})
    assert res.status_code == 403


def test_farmer_cannot_hit_admin(client):
    c, _ids = client
    headers = login(c, "farmer_a")
    res = c.post(
        "/api/users",
        headers=headers,
        json={
            "username": PREFIX + "x",
            "password": "password12",
            "email": f"{PREFIX}x@ex.com",
            "role": "farmer",
            "display_name": "x",
        },
    )
    assert res.status_code == 403


def test_visibility(client):
    c, _ids = client
    fa = login(c, "farmer_a")
    sales = login(c, "sales")
    admin = login(c, "admin")
    ponds_a = c.get("/api/ponds", headers=fa).json()
    assert {p["code"] for p in ponds_a} == {PREFIX + "A"}
    ponds_s = c.get("/api/ponds", headers=sales).json()
    assert {p["code"] for p in ponds_s} == {PREFIX + "A"}
    ponds_admin = c.get("/api/ponds", headers=admin).json()
    codes = {p["code"] for p in ponds_admin}
    assert PREFIX + "A" in codes and PREFIX + "B" in codes
