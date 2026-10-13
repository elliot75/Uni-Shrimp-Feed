#!/usr/bin/env python3
"""Create UPVN_SHRIMP, apply schema, set shrimp_device password, seed admin."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv
from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ADMIN_DB_URL = os.getenv("ADMIN_DATABASE_URL", "")
APP_DB = os.getenv("APP_DATABASE_NAME", "UPVN_SHRIMP")
DEVICE_PASSWORD = os.getenv("SHRIMP_DEVICE_PASSWORD", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
SQL_DIR = ROOT / "backend" / "sql"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main() -> None:
    if not ADMIN_DB_URL:
        print("ADMIN_DATABASE_URL is required", file=sys.stderr)
        sys.exit(1)
    if not DEVICE_PASSWORD:
        print("SHRIMP_DEVICE_PASSWORD is required", file=sys.stderr)
        sys.exit(1)
    if not ADMIN_PASSWORD:
        print("ADMIN_PASSWORD is required", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(ADMIN_DB_URL)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DB,))
    if not cur.fetchone():
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(APP_DB)))
        print(f"created database {APP_DB}")
    else:
        print(f"database {APP_DB} already exists")
    cur.close()
    conn.close()

    conn = psycopg2.connect(ADMIN_DB_URL, dbname=APP_DB)
    conn.autocommit = True
    cur = conn.cursor()
    for sql_path in sorted(SQL_DIR.glob("*.sql")):
        cur.execute(sql_path.read_text(encoding="utf-8"))
        print(f"applied {sql_path.name}")
    cur.execute("ALTER ROLE shrimp_device PASSWORD %s", (DEVICE_PASSWORD,))
    print("schema applied; shrimp_device password set")

    cur.execute("SELECT id FROM shrimp.users WHERE lower(username) = lower(%s)", (ADMIN_USERNAME,))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO shrimp.users (username, email, password_hash, role, display_name, locale)
            VALUES (%s, %s, %s, 'admin', %s, 'zh-TW')
            """,
            (ADMIN_USERNAME, ADMIN_EMAIL, pwd_context.hash(ADMIN_PASSWORD), ADMIN_USERNAME),
        )
        print(f"seeded admin user {ADMIN_USERNAME}")
    else:
        print(f"admin user {ADMIN_USERNAME} already exists")

    cur.close()
    conn.close()
    print("ok")


if __name__ == "__main__":
    main()
