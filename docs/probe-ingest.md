# 探頭資料寫入合約

ESP32 現在可透過 **`POST /api/probe-readings`** 上傳 JSON，由後端呼叫既有 PostgreSQL 寫入函數。主要水溫採用 DO 探頭，MAC 綁池與重送去重規則保持一致。ESP32 只需要後端網址與自己的設備金鑰。

## HTTP POST（ESP32 建議方式）

先套用 `backend/sql/004_device_api_keys.sql`（或執行初始化腳本），並重新啟動更新後的後端。

### 首次安裝：一次性啟用（100 台可使用相同韌體）

先套用 `backend/sql/005_device_activation_codes.sql`，並重啟後端與更新前端。韌體已整合於 `/Users/elliot/ Data/ESP32/shrimp-monitor`；出廠韌體不包含設備金鑰。

1. 管理員在「設備」頁以 ESP32 的 MAC 建立設備、啟用並綁定蝦池。
2. 按「產生啟用碼」並複製。啟用碼有效 15 分鐘、綁定這台 MAC、限兌換一次；再次產生會替換上一組。
3. 首次配網時，連線 ESP32 的 `Shrimp-XXXXXX` 熱點，填入 Wi-Fi、後端網址與啟用碼。已有 Wi-Fi 的設備可開啟 `http://shrimp-XXXXXX.local/setup`，或水質頁上的「設定後端 / 啟用設備」。HTTPS 需填入伺服器根憑證 PEM；區網 HTTP 可留空。
4. ESP32 自行呼叫 `POST /api/devices/activate`，取得專屬金鑰並保存至 NVS。重開機後沿用儲存的設定，自動呼叫讀數 API。

管理員亦可由 API 產生啟用碼：

```bash
curl -X POST "$API_BASE_URL/api/devices/$DEVICE_ID/activation-code" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

回應包含 `device_id`、`device_serial`、`activation_code`、`expires_at`。`DEVICE_ID` 是設備內部 UUID，可由 `GET /api/devices` 取得。啟用碼原文只在產生時回傳，資料庫僅儲存雜湊。

ESP32 不需要管理員 JWT，以啟用碼換取金鑰：

```bash
curl -X POST "$API_BASE_URL/api/devices/activate" \
  -H 'Content-Type: application/json' \
  --data '{"device_serial":"840D8E235164","activation_code":"REPLACE_WITH_THE_GENERATED_CODE"}'
```

成功回傳 HTTP `200`，包含 `device_id`、`device_serial`、`api_key`；先將金鑰寫入 NVS，再刪除暫存啟用碼。伺服器在同一交易內完成金鑰儲存與啟用碼消耗，並鎖定設備與啟用碼，避免併發重複兌換。

- MAC 不符、錯誤、過期或已用過的啟用碼回傳 `401`。
- 設備被停用或解除綁池回傳 `409`，修正狀態後可在到期前重新兌換。
- 產生啟用碼不會中斷原有金鑰；成功兌換時會輪替金鑰，原金鑰立即失效。
- 啟用成功回應若在網路傳輸途中遺失，或 ESP32 無法儲存金鑰，必須重新產生啟用碼。已消耗的啟用碼不會再次回傳金鑰。
- 金鑰與啟用碼不顯示在水質 JSON 或 Serial 診斷中。設定頁與配網熱點供安裝時在可信的區域網路使用。

### 直接產生／輪替金鑰（維護用）

管理員仍可呼叫：

```bash
curl -X POST "$API_BASE_URL/api/devices/$DEVICE_ID/ingest-key" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

回應包含 `device_id`、`device_serial`、`api_key`。此操作輪替既有金鑰並取消這台設備所有待用啟用碼；原文只在本次回應提供，資料庫只儲存 SHA-256 雜湊。一般安裝使用上述一次性啟用流程即可。

### 上傳範例

`API_BASE_URL` 設為後端服務網址，例如區網測試使用 `http://192.168.105.10:8001`，部署時使用已設定有效 TLS 憑證的 HTTPS 網址。`DEVICE_API_KEY` 為上一步回傳的金鑰；不要使用資料庫密碼或管理員 JWT 上傳感測資料。

```bash
curl -X POST "$API_BASE_URL/api/probe-readings" \
  -H 'Content-Type: application/json' \
  -H "X-Device-Key: $DEVICE_API_KEY" \
  --data '{
    "device_serial": "840D8E235164",
    "recorded_at": "2026-10-13T17:30:00+07:00",
    "ph": 8.74,
    "ph_mv": -50.4,
    "ph_temp_c": 25.23,
    "conductivity_us_cm": 26.0,
    "salinity_ppt": 15.84,
    "cond_temp_c": 26.41,
    "tds_mg_l": 16613.7,
    "do_mg_l": 5.62,
    "do_sat_pct": 0.7,
    "do_temp_c": 26.08,
    "raw": {
      "ip": "192.168.105.164",
      "rssi_dbm": -56,
      "hostname": "shrimp-235164.local"
    }
  }'
```

成功回傳 HTTP `200`：

```json
{"id": 123, "device_serial": "840D8E235164", "recorded_at": "2026-10-13T17:30:00+07:00", "temp_c": 26.08}
```

- 必填 `device_serial` 與含時區的 `recorded_at`；其他感測欄位可省略或傳 `null`。MAC 接受 12 位十六進位、冒號或連字號分隔，後端會正規化。
- 金鑰只可替對應的啟用設備上傳；金鑰缺失、錯誤、MAC 不符或設備停用回傳 `401`。
- 設備未綁池回傳 `409`。欄位錯誤、無時區時間、NaN、Infinity、負的濃度／飽和度或超出資料庫格式回傳 `422`。附加欄位必須放 `raw`，不能自行指定 `pond_id`、`cycle_id` 或 `temp_c`。
- 同一 MAC 與量測時間重送回傳既有 `id` 和已儲存的水溫，不覆寫原讀數。ESP32 遇到逾時或 `5xx` 可重試，但要保留同一筆量測原本的 `recorded_at`；收到 `200` 才移除待送資料。
- 後端完成資料庫交易才回覆成功；既有警報 worker 會處理新讀數。
- 在 ESP32 使用 `HTTPClient`：`begin(url)`，加入 `Content-Type: application/json` 和 `X-Device-Key` 標頭，再呼叫 `POST(json)`；HTTPS 請使用 `WiFiClientSecure` 並設定伺服器的 CA 憑證。

## PostgreSQL 直接寫入（既有方式）

原本的直接寫入函數仍可使用，既有資料庫上傳頻率為每 30 分鐘。下方提供舊專案的連線與函數參數對照。

## 連線

環境變數（本系統 `.env`，不要把密碼寫進程式庫）：

| 變數 | 用途 |
|---|---|
| `SHRIMP_DEVICE_URL` | 探頭專用連線字串 |
| `SHRIMP_DEVICE_PASSWORD` | 角色 `shrimp_device` 的密碼 |

連線字串格式：

```
postgresql://shrimp_device:${SHRIMP_DEVICE_PASSWORD}@db.example.com:5432/UPVN_SHRIMP
```

此角色只能 `EXECUTE shrimp.ingest_probe_reading(...)`，不能讀使用者表、不能改池子。

後台先以設備的 Wi-Fi STA MAC 建立設備，再設定可修改的顯示名稱並綁定蝦池。MAC 不受 Wi-Fi 配網或別名影響，資料庫固定正規化為 12 位大寫十六進位（例如 `840D8E235164`）；輸入時也接受冒號或連字號分隔。未登記、未綁池或停用的 MAC 會寫入失敗。

資料庫的 `devices.id` 是內部 UUID 主鍵，`devices.mac_address` 是唯一且不可變的硬體識別碼，`devices.name` 是可在後台變更的別名。每筆讀數以 `device_id` 保留設備關聯；搬池不會改寫歷史讀數。

`003_do_water_temperature.sql` 可直接套用於既有資料庫，歷史讀數的 `temp_c` 也會自動採用各筆 DO 水溫；原始探頭欄位不會被覆寫。

套用資料庫更新請執行 `python3 scripts/init_db.py`。遷移會保留舊序號與歷史讀數；若資料中有重複 MAC 或重複讀數，會停止並提示先處理，不會自行刪除或合併資料。

## 規則

- **一列 = 一台 ESP32 的一個時間點**。pH、電導/鹽度、DO 合併在同一列。
- `recorded_at` 必須是 `timestamptz`，建議帶 `+07`（Asia/Ho_Chi_Minh）。
- 同一設備與 `recorded_at` 重送會回傳既有 id，不會重複列。
- DO 量測值、飽和度與水溫分別寫入 `p_do_mg_l`、`p_do_sat_pct`、`p_do_temp_c`；量測失敗的欄位傳 `NULL`。
- **主要水溫一律使用 DO 探頭**：資料庫 `temp_c` 自動取自 `do_temp_c`，不得手動寫入。DO 水溫缺值時保持 `NULL`，不以 pH 或電導探頭水溫替代；儀表板、最新讀數與歷史圖均採用此欄位。
- pH 與電導探頭水溫仍完整保存，供探頭比對使用。
- 設備 IP、RSSI、mDNS 主機名與其他附加資訊放 `p_raw` jsonb，例如 `{"ip": "192.168.105.164", "rssi_dbm": -56, "hostname": "shrimp-235164.local"}`。
- ESP32 本機網頁每 5 秒更新與資料庫上傳頻率分開設定；既有資料庫上傳頻率維持每 30 分鐘。

## 欄位對照（你現有探頭輸出）

| 探頭 | 範例 | 函數參數 |
|---|---|---|
| pH | 8.74 | `p_ph` |
| 電位 | -50.4 mV | `p_ph_mv` |
| pH 水溫 | 25.23 °C | `p_ph_temp_c` |
| 電導 | 26.0 μS/cm | `p_conductivity_us_cm` |
| 鹽度 | 15.84 ppt | `p_salinity_ppt` |
| 電導水溫 | 26.41 °C | `p_cond_temp_c` |
| TDS | 16613.7 mg/L | `p_tds_mg_l` |
| DO | 5.62 mg/L | `p_do_mg_l` |
| DO 飽和度 | 0.7 % | `p_do_sat_pct` |
| DO 水溫（主要水溫） | 26.08 °C | `p_do_temp_c` |

圖中的電導度以顯示值 `26.0 μS/cm` 原樣示範。上傳程式應確認探頭實際輸出單位；若為 mS/cm，必須先乘以 1000 再寫入 `p_conductivity_us_cm`。DO 飽和度寫入百分比讀數，不自行根據 DO 濃度推算或更正。

## 範例

```sql
SELECT shrimp.ingest_probe_reading(
  p_device_serial       := '840D8E235164',
  p_recorded_at         := TIMESTAMPTZ '2026-10-13 17:30:00+07',
  p_ph                  := 8.74,
  p_ph_mv               := -50.4,
  p_ph_temp_c           := 25.23,
  p_conductivity_us_cm  := 26.0,
  p_salinity_ppt        := 15.84,
  p_cond_temp_c         := 26.41,
  p_tds_mg_l            := 16613.7,
  p_do_mg_l             := 5.62,
  p_do_sat_pct          := 0.7,
  p_do_temp_c           := 26.08,
  p_raw                 := '{"ip":"192.168.105.164","rssi_dbm":-56,"hostname":"shrimp-235164.local"}'::jsonb
);
```

成功回傳 `bigint`（`probe_readings.id`）。未知 serial、未綁池、缺時間戳會丟錯。

Python 範例：

```python
import os
import psycopg2
from psycopg2.extras import Json

conn = psycopg2.connect(os.environ["SHRIMP_DEVICE_URL"])
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(
        """
        SELECT shrimp.ingest_probe_reading(
            p_device_serial := %s,
            p_recorded_at := %s,
            p_ph := %s,
            p_ph_mv := %s,
            p_ph_temp_c := %s,
            p_conductivity_us_cm := %s,
            p_salinity_ppt := %s,
            p_cond_temp_c := %s,
            p_tds_mg_l := %s,
            p_do_mg_l := %s,
            p_do_sat_pct := %s,
            p_do_temp_c := %s,
            p_raw := %s
        )
        """,
        (
            "840D8E235164",
            "2026-10-13 17:30:00+07",
            8.74, -50.4, 25.23,
            26.0, 15.84, 26.41, 16613.7,
            5.62, 0.7, 26.08,
            Json({"ip": "192.168.105.164", "rssi_dbm": -56, "hostname": "shrimp-235164.local"}),
        ),
    )
    reading_id = cur.fetchone()[0]
conn.close()
```
