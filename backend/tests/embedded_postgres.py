"""Minimal DB-API adapter to the test-only, in-memory PostgreSQL WASM engine."""
import json
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        def encode(value):
            return value.isoformat() if hasattr(value, "isoformat") else str(value)

        proc = self.connection.process
        # psycopg2 adapts aware datetimes as typed timestamptz literals. Preserve
        # that type when using PGlite's prepared parameters (notably + interval).
        casts = ["::timestamptz" if isinstance(value, datetime) else "" for value in params]
        proc.stdin.write(json.dumps({"sql": sql, "params": params, "casts": casts}, default=encode) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("Embedded PostgreSQL exited unexpectedly")
        result = json.loads(line)
        if "error" in result:
            raise AssertionError(result["error"])
        self.rows = result["rows"]
        for field in result["fields"]:
            for row in self.rows:
                key, oid = field["name"], field["dataTypeID"]
                if row[key] is None:
                    continue
                if oid == 1700:
                    row[key] = Decimal(row[key])
                elif oid == 1184:
                    row[key] = datetime.fromisoformat(row[key].replace("Z", "+00:00"))
                elif oid == 20:
                    row[key] = int(row[key])

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows


class EmbeddedPostgres:
    def __init__(self):
        if not shutil.which("node") or not (ROOT / "node_modules/@electric-sql/pglite").is_dir():
            pytest.fail("NH3 SQL tests require Node and `npm ci` at the repository root")
        self.process = subprocess.Popen(
            ["node", str(Path(__file__).with_name("pglite_bridge.mjs"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT,
        )

    def cursor(self, **kwargs):
        return Cursor(self)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def commit(self):
        with self.cursor() as cur:
            cur.execute("COMMIT")
