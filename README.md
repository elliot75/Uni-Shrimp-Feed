# Uni-Shrimp

Uni-President「3 Tốt」養蝦水質監測後台。ESP32 探頭透過 HTTP POST API 寫入 PostgreSQL（也保留直接寫入函數），本系統提供登入、多池、養殖週期、人工試劑、警報（站內 / Email / Telegram）與越中雙語界面。

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

見 [docs/probe-ingest.md](docs/probe-ingest.md)。ESP32 使用 `POST /api/probe-readings`，以 `X-Device-Key` 傳送各設備專屬金鑰。管理員在設備頁產生 15 分鐘有效的一次性啟用碼，ESP32 首次配網時以 `POST /api/devices/activate` 換取金鑰並存入 NVS；所有設備可使用相同韌體。先套用 `backend/sql/004_device_api_keys.sql`、`005_device_activation_codes.sql` 並重新啟動後端。管理員仍可使用 `POST /api/devices/{device_id}/ingest-key` 直接輪替金鑰。既有 `shrimp_device` 直接呼叫 `shrimp.ingest_probe_reading(...)` 的方式仍保留。

主要水溫使用 DO 探頭的 `do_temp_c`，由資料庫自動產生 `temp_c`；缺值時不以其他探頭水溫替代。儀表板與蝦池頁顯示 pH、電位、DO、飽和度、鹽度、電導度、TDS 與水溫，並保留 pH／電導探頭水溫。既有資料庫需套用 `backend/sql/003_do_water_temperature.sql`（或執行初始化腳本）。

## 測試

```bash
cd backend && SKIP_WORKER=1 pytest -q
```

上方整合測試會使用 `.env` 的資料庫，建立與刪除測試資料；請使用測試資料庫，並停用 SMTP / Telegram 通知。僅執行不需資料庫的測試：

```bash
cd backend && pytest -q tests/test_alerts.py tests/test_review_regressions.py
```

`tests/test_sensor_readings.py` 檢查完整感測資料與 DO 水溫規則，使用唯一測試資料並在交易結束後回滾，不會刪除既有設備或讀數。
