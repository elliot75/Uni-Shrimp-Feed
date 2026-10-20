# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Python 3.11 is required (psycopg2 wheels). Node 18+. Config lives in the repo-root `.env` (copy from `.env.sample`); never commit it. `ADMIN_DATABASE_URL`, `SHRIMP_DEVICE_PASSWORD`, `ADMIN_PASSWORD`, and `JWT_SECRET` must be set. The backend loads that file itself, so it does not need to be exported.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python3 scripts/init_db.py          # also: npm run init-db
cd backend && uvicorn main:app --reload --port 8001
cd frontend && npm install && npm run dev
```

- API: http://localhost:8001/api/health — Web: http://localhost:5174 (Vite proxies `/api` to port 8001)
- Admin login is `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`
- Docker: `docker compose up --build` (frontend 8081, backend 8001→container 8000). Production is `compose.production.yml` (external network `uni-services_backend`, backend host port 8002 by default).

Tests run from `backend/` (`pytest.ini` sets `pythonpath = .`). There is no linter and no frontend test runner.

```bash
cd backend && SKIP_WORKER=1 pytest -q                          # full suite; uses .env database
cd backend && SKIP_WORKER=1 pytest -q tests/test_alerts.py     # one file
cd backend && SKIP_WORKER=1 pytest -q tests/test_alerts.py::test_name
cd backend && pytest -q tests/test_alerts.py tests/test_review_regressions.py tests/test_water_quality.py tests/test_password.py
```

The last command is the database-free subset. The rest create and delete rows in the database named by `.env` — use a test database and leave SMTP / Telegram unset. `tests/test_sensor_readings.py` rolls back its transaction and does not delete existing devices or readings. `SKIP_WORKER=1` stops the 15-second alert worker from starting with the app.

## Architecture

Uni-President「3 Tốt」shrimp water-quality monitor. ESP32 probes post readings; this app stores them in PostgreSQL and serves a Vietnamese / Traditional Chinese UI with login, ponds, culture cycles, manual reagent tests, and alerts (in-app, email, Telegram). Probe firmware is a separate tree; the ingest contract is [docs/probe-ingest.md](docs/probe-ingest.md).

All application tables and functions live in the `shrimp` schema of database `UPVN_SHRIMP`. `backend/db.py` sets `search_path` to `shrimp, public` and returns `RealDictCursor` connections. There is no ORM — routers and `alerts.py` use raw SQL.

`scripts/init_db.py` creates the database, applies every file in `backend/sql/` in filename order, sets the `shrimp_device` role password, and seeds the admin user. Those files are re-applied on every init, so they must stay idempotent (`IF NOT EXISTS`, `ON CONFLICT`, `CREATE OR REPLACE`). Later files replace functions defined earlier. The live definitions of `shrimp.cycle_for_sample` and `shrimp.ingest_probe_reading` are the ones in `009_cycle_end_and_sessions.sql`; editing only `001_init.sql` does nothing on an existing database.

### Ingest

`POST /api/probe-readings` (`backend/routers/probe_readings.py`) authenticates with `X-Device-Key`, hashes it (SHA-256, same as activation codes), and calls `shrimp.ingest_probe_reading`. The function binds the reading to the device's current pond and to the cycle covering that sample time, and is idempotent on `(device, recorded_at)` — a retry returns the existing id and does not overwrite. `shrimp_device` can only `EXECUTE` that function; the direct-SQL path is still supported.

Device identity is the Wi-Fi STA MAC, normalized to 12 uppercase hex digits (`shrimp.normalize_device_mac`, mirrored in `models.py`). `devices.mac_address` is a generated column and a trigger makes it immutable. `devices.id` is the internal UUID; moving a device does not rewrite historical readings. First install: an admin mints a 15-minute one-time activation code, the ESP32 exchanges it at `POST /api/devices/activate` (device row locked before the code row), and the plaintext key is returned once. Keys and codes are stored only as hashes.

`probe_readings.temp_c` is `GENERATED ALWAYS AS (do_temp_c)`. Missing DO temperature stays NULL — do not substitute pH or conductivity probe temperature. Probe raw values are never rewritten. `water_quality.py` only annotates: Emerson/Whitfield unionized ammonia, Garcia–Gordon theoretical DO saturation (display comparison only, never an alert), and diurnal pH swing in `Asia/Ho_Chi_Minh` (morning 05–07, afternoon 13–16).

### Alerts

`main.py` starts a worker every 15 seconds (`SKIP_WORKER=1` disables it). It calls `process_pending_readings` (rows with `alerts_evaluated_at IS NULL`), `evaluate_stale_devices`, then `flush_notifications` / `retry_unnotified`, and polls Telegram for `/start <bind code>`. Evaluation is in `alerts.py`: probe rules (pH, DO), lab rules (alkalinity, Ca/Mg/K, NO2, TAN), and `DEVICE_STALE`. Thresholds live in `shrimp.alert_rules` (seeded by `001` and `006`); the handbook TAN×pH table is `shrimp.nh3_lookup` and is the range gate — the Emerson formula does not replace it. Open alerts are unique on `(pond_id, rule_code)`. Grow-out cycles with `sample_avg_weight_g >= 10` use the `*_10G` mineral rules. Notifications go to the pond's farmer plus assigned salespeople, with a 2-hour cooldown.

### Access and UI

Roles are `admin`, `salesperson`, `farmer`. `access.py` scopes ponds: admin sees all, a farmer sees their own, a salesperson sees farmers linked in `salesperson_farmers`. JWT (`auth.py`, HS256) carries `token_version`; password changes bump it so old tokens die. Cycle day boundaries and sample-to-cycle assignment use `Asia/Ho_Chi_Minh`, not the database timezone. One active cycle per pond.

The frontend (`frontend/src`) is React 19, Vite 6, Tailwind 4, react-router 7. No component library. `api/client.js` sends the JWT from `localStorage` and redirects to `/login` on 401. Strings are the `vi` / `zh-TW` dictionaries in `i18n.js`. Admin-only routes are `/users` and `/rules`.
