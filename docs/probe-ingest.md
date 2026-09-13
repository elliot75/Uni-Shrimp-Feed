# 探頭資料寫入合約

另一個 ESP32 專案**直接連 PostgreSQL**，每 30 分鐘呼叫一次寫入函數。不要用後台 HTTP，也不要用 `upvnbd` 超管帳。

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

後台必須先建立 `shrimp.devices.serial`，並把該設備綁到一口池。未綁定或停用的 serial 會寫入失敗。

## 規則

- **一列 = 一台 ESP32 的一個時間點**。pH、電導/鹽度、DO 合併在同一列。
- `recorded_at` 必須是 `timestamptz`，建議帶 `+07`（Asia/Ho_Chi_Minh）。
- 同一 `(device_serial, recorded_at)` 重送會回傳既有 id，不會重複列。
- DO 還沒接好時，三個 DO 參數傳 `NULL`。
- 多餘欄位放 `p_raw` jsonb。

## 欄位對照（你現有探頭輸出）

| 探頭 | 範例 | 函數參數 |
|---|---|---|
| pH | 9.01 | `p_ph` |
| 電位 | -65.68 mV | `p_ph_mv` |
| pH 水溫 | 25.10 °C | `p_ph_temp_c` |
| 電導 | 29642.26 μS/cm | `p_conductivity_us_cm` |
| 鹽度 | 18.33 ppt | `p_salinity_ppt` |
| 電導水溫 | 26.10 °C | `p_cond_temp_c` |
| TDS | 18971.04 mg/L | `p_tds_mg_l` |
| DO | （尚未） | `p_do_mg_l` |
| DO 飽和度 | （尚未） | `p_do_sat_pct` |
| DO 水溫 | （尚未） | `p_do_temp_c` |

## 範例

```sql
SELECT shrimp.ingest_probe_reading(
  p_device_serial       := 'ESP32-TEST-01',
  p_recorded_at         := TIMESTAMPTZ '2026-09-12 17:30:00+07',
  p_ph                  := 9.01,
  p_ph_mv               := -65.68,
  p_ph_temp_c           := 25.10,
  p_conductivity_us_cm  := 29642.26,
  p_salinity_ppt        := 18.33,
  p_cond_temp_c         := 26.10,
  p_tds_mg_l            := 18971.04,
  p_do_mg_l             := NULL,
  p_do_sat_pct          := NULL,
  p_do_temp_c           := NULL,
  p_raw                 := NULL
);
```

成功回傳 `bigint`（`probe_readings.id`）。未知 serial、未綁池、缺時間戳會丟錯。

Python 範例：

```python
import os
import psycopg2

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
            "ESP32-TEST-01",
            "2026-09-12 17:30:00+07",
            9.01, -65.68, 25.10,
            29642.26, 18.33, 26.10, 18971.04,
            None, None, None, None,
        ),
    )
    reading_id = cur.fetchone()[0]
conn.close()
```
