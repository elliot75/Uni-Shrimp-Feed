# Uni-Shrimp

Uni-President「3 Tốt」養蝦水質監測後台。探頭由另一專案直接寫入 PostgreSQL，本系統提供登入、多池、養殖週期、人工試劑、警報（站內 / Email / Telegram）與越中雙語界面。

## 啟動

需要 Python 3.11（psycopg2 輪子）與 Node 18+。

```bash
cp .env.sample .env   # 填入資料庫、JWT、SMTP、Telegram
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python3 scripts/init_db.py
cd backend && uvicorn main:app --reload --port 8001
# 另開終端
cd frontend && npm install && npm run dev
```

- API: http://localhost:8001/api/health
- Web: http://localhost:5174
- 管理員帳密見 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`

必須自行設定 `ADMIN_DATABASE_URL`、`SHRIMP_DEVICE_PASSWORD`、`ADMIN_PASSWORD` 與 `JWT_SECRET`；範例檔不包含可用帳密。可使用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` 產生 JWT 密鑰。

Docker：`docker compose up --build`（前端 8081，後端 8001）。

## 探頭寫入

見 [docs/probe-ingest.md](docs/probe-ingest.md)。使用角色 `shrimp_device` 呼叫 `shrimp.ingest_probe_reading(...)`。

## 測試

```bash
cd backend && SKIP_WORKER=1 pytest -q
```

上方整合測試會使用 `.env` 的資料庫，建立與刪除測試資料；請使用測試資料庫，並停用 SMTP / Telegram 通知。僅執行不需資料庫的測試：

```bash
cd backend && pytest -q tests/test_alerts.py tests/test_review_regressions.py
```
