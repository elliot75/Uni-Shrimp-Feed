"""Evaluate handbook thresholds and send notifications."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import logging
from weakref import WeakKeyDictionary

from access import farmer_ids_for_salesperson
from email_service import send_email
from telegram_service import send_message
from lab_samples import load_sample_conditions
from water_quality import assess_nh3, diurnal_swing, interpolate_nh3

NOTIFY_COOLDOWN = timedelta(hours=2)
STALE_DEFAULT_MINUTES = 60
logger = logging.getLogger(__name__)
_PERMANENT_NOTIFY_ERRORS = {
    "smtp not configured",
    "telegram not configured",
    "missing recipient",
    "missing chat_id",
}
_notification_queues = WeakKeyDictionary()


def _num(value) -> float | None:
    if value is None:
        return None
    return float(value)


def uses_10g_thresholds(cycle: dict | None) -> bool:
    if not cycle:
        return False
    weight = _num(cycle.get("sample_avg_weight_g"))
    return weight is not None and weight >= 10


def water_change_pct(cycle: dict | None) -> int:
    if cycle and cycle.get("stage") == "nursery":
        return 20
    return 40


def load_rules(conn) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM shrimp.alert_rules WHERE is_active = true")
        return {row["code"]: dict(row) for row in cur.fetchall()}


def load_lookup(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT tan_ppm, ph, nh3_ppm FROM shrimp.nh3_lookup")
        return [dict(r) for r in cur.fetchall()]


def load_active_cycle(conn, pond_id) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM shrimp.cycles WHERE pond_id = %s AND status = 'active' LIMIT 1",
            (pond_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def load_pond(conn, pond_id) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM shrimp.ponds WHERE id = %s", (pond_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def recipients_for_pond(conn, pond: dict, severity: str) -> list[dict]:
    users = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, locale, telegram_chat_id, role, is_active, display_name
            FROM shrimp.users WHERE id = %s AND is_active = true
            """,
            (pond["farmer_id"],),
        )
        farmer = cur.fetchone()
        if farmer:
            users.append(dict(farmer))
        cur.execute(
            """
            SELECT u.id, u.email, u.locale, u.telegram_chat_id, u.role, u.is_active, u.display_name
            FROM shrimp.users u
            JOIN shrimp.salesperson_farmers sf ON sf.salesperson_id = u.id
            WHERE sf.farmer_id = %s AND u.is_active = true
            """,
            (pond["farmer_id"],),
        )
        users.extend(dict(r) for r in cur.fetchall())
        if severity == "critical":
            cur.execute(
                """
                SELECT id, email, locale, telegram_chat_id, role, is_active, display_name
                FROM shrimp.users WHERE role = 'admin' AND is_active = true
                """
            )
            users.extend(dict(r) for r in cur.fetchall())
    seen = set()
    out = []
    for u in users:
        key = str(u["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def _log_notification(conn, alert_id, user_id, channel, success, error):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shrimp.notification_log (alert_event_id, user_id, channel, success, error)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (alert_id, user_id, channel, success, error),
        )


def _sent_recently(conn, alert_id, user_id, channel) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM shrimp.notification_log
            WHERE alert_event_id = %s AND user_id = %s AND channel = %s
              AND success AND created_at > now() - interval '2 hours'
            LIMIT 1
            """,
            (alert_id, user_id, channel),
        )
        return cur.fetchone() is not None


def notify_alert(conn, event: dict, pond: dict) -> None:
    people = recipients_for_pond(conn, pond, event["severity"])
    subject = f"[Uni-Shrimp] {event['rule_code']} · {pond.get('code')}"
    retryable = False
    for person in people:
        locale = person.get("locale") or "vi"
        body = event["message_vi"] if locale == "vi" else event["message_zh"]
        text = f"{pond.get('code')} {pond.get('name')}\n{body}"
        html = (
            f"<p><b>{escape(str(pond.get('code') or ''))}</b> "
            f"{escape(str(pond.get('name') or ''))}</p><p>{escape(str(body))}</p>"
        )
        if _sent_recently(conn, event["id"], person["id"], "email"):
            email_ok, email_err = True, None
        else:
            email_ok, email_err = send_email(person.get("email"), subject, html)
            _log_notification(conn, event["id"], person["id"], "email", email_ok, email_err)
        if not email_ok and email_err not in _PERMANENT_NOTIFY_ERRORS:
            retryable = True
        if _sent_recently(conn, event["id"], person["id"], "telegram"):
            tg_ok, tg_err = True, None
        else:
            tg_ok, tg_err = send_message(person.get("telegram_chat_id"), text)
            _log_notification(conn, event["id"], person["id"], "telegram", tg_ok, tg_err)
        if not tg_ok and tg_err not in _PERMANENT_NOTIFY_ERRORS:
            retryable = True
    if retryable:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE shrimp.alert_events
            SET last_notified_at = now(), notify_count = notify_count + 1
            WHERE id = %s
            """,
            (event["id"],),
        )


def _queue_notification(conn, event: dict, pond: dict) -> None:
    queued = _notification_queues.get(conn)
    if queued is None:
        queued = []
        _notification_queues[conn] = queued
    queued.append((event, pond))


def flush_notifications(conn) -> None:
    """Send queued alerts after the caller's transaction has committed."""
    queued = _notification_queues.pop(conn, None)
    if not isinstance(queued, list) or not queued:
        return
    try:
        for event, pond in queued:
            notify_alert(conn, event, pond)
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Alert notification failed; it will be retried")


def retry_unnotified(conn, limit: int = 50) -> None:
    """Deliver alerts saved before a crash, after the reading itself was already evaluated."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.alert_events
            WHERE resolved_at IS NULL
              AND last_notified_at IS NULL
              AND opened_at > now() - interval '7 days'
            ORDER BY opened_at
            LIMIT %s
            """,
            (limit,),
        )
        events = [dict(row) for row in cur.fetchall()]
    if not events:
        return
    try:
        for event in events:
            pond = load_pond(conn, event["pond_id"])
            if pond:
                notify_alert(conn, event, pond)
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Alert notification retry failed")


def _should_notify(event: dict) -> bool:
    last = event.get("last_notified_at")
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= NOTIFY_COOLDOWN


def upsert_alert(conn, pond, cycle, rule, value, message_vi, message_zh) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.alert_events
            WHERE pond_id = %s AND rule_code = %s AND resolved_at IS NULL
            """,
            (pond["id"], rule["code"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE shrimp.alert_events
                SET cycle_id = %s, severity = %s, metric = %s, value = %s,
                    message_vi = %s, message_zh = %s
                WHERE id = %s RETURNING *
                """,
                (cycle["id"] if cycle else None, rule["severity"], rule["metric"],
                 value, message_vi, message_zh, existing["id"]),
            )
            event = dict(cur.fetchone())
            if _should_notify(event):
                _queue_notification(conn, event, pond)
            return
        cur.execute(
            """
            INSERT INTO shrimp.alert_events (
                pond_id, cycle_id, rule_code, severity, metric, value,
                message_vi, message_zh
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                pond["id"],
                cycle["id"] if cycle else None,
                rule["code"],
                rule["severity"],
                rule["metric"],
                value,
                message_vi,
                message_zh,
            ),
        )
        event = dict(cur.fetchone())
    _queue_notification(conn, event, pond)


def resolve_alert(conn, pond_id, rule_code) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE shrimp.alert_events
            SET resolved_at = now()
            WHERE pond_id = %s AND rule_code = %s AND resolved_at IS NULL
            """,
            (pond_id, rule_code),
        )


def _msg(code, value, extra_vi="", extra_zh="", threshold=None):
    shown = f"{value:.2f}" if isinstance(value, (int, float, Decimal)) else ("—" if value is None else str(value))
    limits = {
        "PH_LOW": 7.6, "PH_HIGH": 7.8, "ALK_LOW": 150,
        "CA_LOW_NURSERY": 240, "CA_LOW_GROWOUT": 160, "CA_LOW_10G": 200,
        "MG_LOW_NURSERY": 550, "MG_LOW_GROWOUT": 400, "MG_LOW_10G": 450,
        "NO2_HIGH": 7, "NO2_HARVEST_EARLY": 7, "DEVICE_STALE": 60,
    }
    limit = f"{float(threshold if threshold is not None else limits.get(code, 0)):g}"
    vi = {
        "PH_LOW": f"pH {shown} thấp hơn {limit}.",
        "PH_HIGH": f"pH {shown} cao hơn {limit}.",
        "DO_LOW": f"DO {shown} mg/L thấp.",
        "DO_CRITICAL": f"DO {shown} mg/L rất thấp.",
        "ALK_LOW": f"Độ kiềm {shown} ppm < {limit}.",
        "CA_LOW_NURSERY": f"Ca {shown} ppm < {limit} (ao gièo).",
        "CA_LOW_GROWOUT": f"Ca {shown} ppm < {limit} (ao nuôi).",
        "CA_LOW_10G": f"Ca {shown} ppm < {limit} (tôm ≥ 10g).",
        "MG_LOW_NURSERY": f"Mg {shown} ppm < {limit} (ao gièo).",
        "MG_LOW_GROWOUT": f"Mg {shown} ppm < {limit} (ao nuôi).",
        "MG_LOW_10G": f"Mg {shown} ppm < {limit} (tôm ≥ 10g).",
        "NO2_HIGH": f"NO₂ {shown} ppm ≥ {limit}.",
        "NO2_HARVEST_EARLY": f"NO₂ > {limit} ppm liên tục 7 ngày. Nên cân nhắc thu tỉa sớm.",
        "NH3_WARN": f"NH₃ không ion hóa {shown} ppm (cảnh báo).",
        "NH3_DANGER": f"NH₃ không ion hóa {shown} ppm (độc hại).",
        "NH3_OUT_OF_RANGE": "Không thể xác định NH₃ không ion hóa: thiếu pH gần thời điểm lấy mẫu, hoặc TAN/pH nằm ngoài phạm vi bảng hướng dẫn.",
        "K_LOW": f"K⁺ {shown} ppm < {limit}.",
        "DEVICE_STALE": f"Thiết bị không gửi dữ liệu hơn {limit} phút.",
    }
    zh = {
        "PH_LOW": f"pH {shown} 低於 {limit}。",
        "PH_HIGH": f"pH {shown} 高於 {limit}。",
        "DO_LOW": f"DO {shown} mg/L 偏低。",
        "DO_CRITICAL": f"DO {shown} mg/L 過低。",
        "ALK_LOW": f"鹼度 {shown} ppm < {limit}。",
        "CA_LOW_NURSERY": f"Ca {shown} ppm < {limit}（育苗池）。",
        "CA_LOW_GROWOUT": f"Ca {shown} ppm < {limit}（養成池）。",
        "CA_LOW_10G": f"Ca {shown} ppm < {limit}（蝦 ≥ 10g）。",
        "MG_LOW_NURSERY": f"Mg {shown} ppm < {limit}（育苗池）。",
        "MG_LOW_GROWOUT": f"Mg {shown} ppm < {limit}（養成池）。",
        "MG_LOW_10G": f"Mg {shown} ppm < {limit}（蝦 ≥ 10g）。",
        "NO2_HIGH": f"NO₂ {shown} ppm ≥ {limit}。",
        "NO2_HARVEST_EARLY": f"NO₂ 連續 7 天 > {limit} ppm，建議考慮提前收成。",
        "NH3_WARN": f"未電離 NH₃ {shown} ppm（警告）。",
        "NH3_DANGER": f"未電離 NH₃ {shown} ppm（有害）。",
        "NH3_OUT_OF_RANGE": "未電離 NH₃ 無法判定：採樣時缺少附近的 pH，或 TAN／pH 超出手冊表格範圍。",
        "K_LOW": f"K⁺ {shown} ppm < {limit}。",
        "DEVICE_STALE": f"設備超過 {limit} 分鐘未回報。",
    }
    return vi.get(code, code) + extra_vi, zh.get(code, code) + extra_zh


def evaluate_probe_reading(conn, reading: dict) -> None:
    pond = load_pond(conn, reading["pond_id"])
    if not pond:
        return
    cycle = load_active_cycle(conn, pond["id"])
    rules = load_rules(conn)
    ph = _num(reading.get("ph"))
    do_v = _num(reading.get("do_mg_l"))

    def handle(code, firing, value):
        rule = rules.get(code)
        if not rule:
            return
        if firing:
            extra_vi = extra_zh = ""
            if code == "PH_LOW":
                extra_vi = " Theo sổ tay, sử dụng CaO để điều chỉnh pH."
                extra_zh = " 手冊建議使用 CaO 調整 pH。"
            elif code == "PH_HIGH":
                extra_vi = " Theo sổ tay, tăng liều mật đường."
                extra_zh = " 手冊建議增加糖蜜用量。"
            if code.startswith("PH"):
                swing = _today_swing(conn, pond["id"])
                if swing and swing.get("delta_ph") is not None:
                    delta = swing["delta_ph"]
                    extra_vi += f" Biên độ pH trong ngày {delta:+.2f}."
                    extra_zh += f" 今日 pH 波動 {delta:+.2f}。"
            threshold = rule.get("min_value" if "LOW" in code or code == "DO_CRITICAL" else "max_value")
            vi, zh = _msg(code, value, extra_vi, extra_zh, threshold)
            upsert_alert(conn, pond, cycle, rule, value, vi, zh)
        else:
            resolve_alert(conn, pond["id"], code)

    latest = _latest_probe_metrics(conn, pond["id"])
    current_ph = ph is not None and latest.get("ph") == reading.get("id")
    current_do = do_v is not None and latest.get("do_mg_l") == reading.get("id")
    if current_ph:
        handle("PH_LOW", ph < _num(rules.get("PH_LOW", {}).get("min_value")) if rules.get("PH_LOW") else False, ph)
        handle("PH_HIGH", ph > _num(rules.get("PH_HIGH", {}).get("max_value")) if rules.get("PH_HIGH") else False, ph)
    if current_do:
        crit = rules.get("DO_CRITICAL")
        low = rules.get("DO_LOW")
        handle("DO_CRITICAL", bool(crit) and do_v < _num(crit["min_value"]), do_v)
        handle("DO_LOW", bool(low) and do_v < _num(low["min_value"]) and not (crit and do_v < _num(crit["min_value"])), do_v)
    if any(reading.get(field) is not None for field in ("ph", "do_temp_c", "salinity_ppt")):
        reevaluate_tan_for_probe(conn, reading)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shrimp.probe_readings SET alerts_evaluated_at = now() WHERE id = %s",
            (reading["id"],),
        )


def _latest_probe_metrics(conn, pond_id) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT id FROM shrimp.probe_readings WHERE pond_id = %s AND ph IS NOT NULL
               AND recorded_at <= now() + interval '5 minutes'
               ORDER BY recorded_at DESC, id DESC LIMIT 1) AS ph,
              (SELECT id FROM shrimp.probe_readings WHERE pond_id = %s AND do_mg_l IS NOT NULL
               AND recorded_at <= now() + interval '5 minutes'
               ORDER BY recorded_at DESC, id DESC LIMIT 1) AS do_mg_l
            """,
            (pond_id, pond_id),
        )
        row = cur.fetchone()
        return dict(row) if row else {"ph": None, "do_mg_l": None}


def _today_swing(conn, pond_id) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT recorded_at, ph, do_mg_l
            FROM shrimp.probe_readings
            WHERE pond_id = %s
              AND recorded_at <= now() + interval '5 minutes'
              AND (recorded_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                  = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
            ORDER BY recorded_at
            """,
            (pond_id,),
        )
        rows = cur.fetchall()
    if not isinstance(rows, list):
        return None
    return diurnal_swing(rows)


def _nh3_note(temp_used: bool, salinity_used: bool, outside: bool, emerson) -> tuple[str, str]:
    if outside:
        if emerson is None:
            return (" Ngoài phạm vi bảng sổ tay.", " 超出手冊表格範圍。")
        shown = f"{emerson:.3f}"
        return (
            f" Ngoài phạm vi bảng sổ tay. Ước tính theo nhiệt độ {shown} ppm, không dùng làm ngưỡng.",
            f" 超出手冊表格範圍。水溫估算 {shown} ppm，不作為閾值。",
        )
    if temp_used and salinity_used:
        return (" Đã hiệu chỉnh theo nhiệt độ và độ mặn.", " 已依水溫與鹽度修正。")
    if temp_used:
        return (" Đã hiệu chỉnh theo nhiệt độ; chưa có độ mặn.", " 已依水溫修正，未計鹽度。")
    return (" Chưa hiệu chỉnh nhiệt độ.", " 未作水溫修正。")


def consecutive_no2_days(conn, pond_id, threshold: float, cycle_id=None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON ((sampled_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
                   (sampled_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS d, no2_ppm AS no2
            FROM shrimp.lab_tests
            WHERE pond_id = %s AND cycle_id IS NOT DISTINCT FROM %s AND no2_ppm IS NOT NULL
              AND sampled_at <= now() + interval '5 minutes'
            ORDER BY (sampled_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date DESC,
                     sampled_at DESC, created_at DESC, id DESC
            LIMIT 14
            """,
            (pond_id, cycle_id),
        )
        rows = cur.fetchall()
    streak = 0
    expected = date.today()
    # allow latest sample date to start streak even if not today
    if rows:
        expected = rows[0]["d"]
    for row in rows:
        if row["d"] != expected:
            break
        if _num(row["no2"]) > threshold:
            streak += 1
            expected = expected - timedelta(days=1)
        else:
            break
    return streak


def _latest_lab_metrics(conn, pond_id, cycle_id=None) -> dict:
    fields = ("no2_ppm", "nh3_ppm", "alkalinity_ppm", "ca_ppm", "mg_ppm", "k_ppm")
    latest = ", ".join(
        f"(SELECT id FROM shrimp.lab_tests WHERE pond_id = %s AND cycle_id IS NOT DISTINCT FROM %s "
        f"AND {field} IS NOT NULL AND sampled_at <= now() + interval '5 minutes' "
        f"ORDER BY sampled_at DESC, created_at DESC, id DESC LIMIT 1) AS {field}"
        for field in fields
    )
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {latest}",
            (pond_id, cycle_id) * len(fields),
        )
        row = cur.fetchone()
        return dict(row) if row else {field: None for field in fields}


def evaluate_lab_test(conn, lab: dict) -> None:
    pond = load_pond(conn, lab["pond_id"])
    if not pond:
        return
    cycle = load_active_cycle(conn, pond["id"])
    rules = load_rules(conn)
    lookup = load_lookup(conn)
    lab_cycle_id = lab.get("cycle_id")
    latest = _latest_lab_metrics(conn, pond["id"], lab_cycle_id)
    active_cycle_id = (cycle or {}).get("id")
    lab_cycle_is_active = (str(lab_cycle_id) if lab_cycle_id is not None else None) == (
        str(active_cycle_id) if active_cycle_id is not None else None
    )
    stage = (cycle or {}).get("stage") or ("nursery" if pond["pond_type"] == "nursery" else "growout")
    big = uses_10g_thresholds(cycle)

    def handle(code, firing, value, extra=("", "")):
        rule = rules.get(code)
        if not rule:
            return
        if firing:
            threshold = rule.get("min_value" if "LOW" in code or code == "DO_CRITICAL" else "max_value")
            vi, zh = _msg(code, value, extra[0], extra[1], threshold)
            upsert_alert(conn, pond, cycle, rule, value, vi, zh)
        else:
            resolve_alert(conn, pond["id"], code)

    def current(field):
        return (
            lab_cycle_is_active
            and lab.get(field) is not None
            and latest.get(field) == lab.get("id")
        )

    alk = _num(lab.get("alkalinity_ppm")) if current("alkalinity_ppm") else None
    if alk is not None and rules.get("ALK_LOW"):
        handle("ALK_LOW", alk < _num(rules["ALK_LOW"]["min_value"]), alk)

    ca = _num(lab.get("ca_ppm")) if current("ca_ppm") else None
    if ca is not None:
        if big and rules.get("CA_LOW_10G"):
            handle("CA_LOW_10G", ca < _num(rules["CA_LOW_10G"]["min_value"]), ca)
            resolve_alert(conn, pond["id"], "CA_LOW_NURSERY")
            resolve_alert(conn, pond["id"], "CA_LOW_GROWOUT")
        elif stage == "nursery" and rules.get("CA_LOW_NURSERY"):
            handle("CA_LOW_NURSERY", ca < _num(rules["CA_LOW_NURSERY"]["min_value"]), ca)
            resolve_alert(conn, pond["id"], "CA_LOW_GROWOUT")
            resolve_alert(conn, pond["id"], "CA_LOW_10G")
        elif rules.get("CA_LOW_GROWOUT"):
            handle("CA_LOW_GROWOUT", ca < _num(rules["CA_LOW_GROWOUT"]["min_value"]), ca)
            resolve_alert(conn, pond["id"], "CA_LOW_NURSERY")
            resolve_alert(conn, pond["id"], "CA_LOW_10G")

    mg = _num(lab.get("mg_ppm")) if current("mg_ppm") else None
    if mg is not None:
        if big and rules.get("MG_LOW_10G"):
            handle("MG_LOW_10G", mg < _num(rules["MG_LOW_10G"]["min_value"]), mg)
            resolve_alert(conn, pond["id"], "MG_LOW_NURSERY")
            resolve_alert(conn, pond["id"], "MG_LOW_GROWOUT")
        elif stage == "nursery" and rules.get("MG_LOW_NURSERY"):
            handle("MG_LOW_NURSERY", mg < _num(rules["MG_LOW_NURSERY"]["min_value"]), mg)
            resolve_alert(conn, pond["id"], "MG_LOW_GROWOUT")
            resolve_alert(conn, pond["id"], "MG_LOW_10G")
        elif rules.get("MG_LOW_GROWOUT"):
            handle("MG_LOW_GROWOUT", mg < _num(rules["MG_LOW_GROWOUT"]["min_value"]), mg)
            resolve_alert(conn, pond["id"], "MG_LOW_NURSERY")
            resolve_alert(conn, pond["id"], "MG_LOW_10G")

    no2 = _num(lab.get("no2_ppm")) if current("no2_ppm") else None
    if no2 is not None and rules.get("NO2_HIGH"):
        handle("NO2_HIGH", no2 >= _num(rules["NO2_HIGH"]["max_value"]), no2)
    # A backfilled day can complete or break the streak without being the latest sample.
    if lab.get("no2_ppm") is not None and lab_cycle_is_active and rules.get("NO2_HARVEST_EARLY"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT no2_ppm FROM shrimp.lab_tests
                WHERE pond_id = %s AND cycle_id IS NOT DISTINCT FROM %s AND no2_ppm IS NOT NULL
                  AND sampled_at <= now() + interval '5 minutes'
                ORDER BY sampled_at DESC, created_at DESC, id DESC LIMIT 1
                """,
                (pond["id"], lab_cycle_id),
            )
            newest = cur.fetchone()
        if newest:
            streak = consecutive_no2_days(
                conn, pond["id"], _num(rules["NO2_HARVEST_EARLY"]["max_value"]), lab_cycle_id
            )
            handle("NO2_HARVEST_EARLY", streak >= 7, _num(newest["no2_ppm"]))

    tan = _num(lab.get("nh3_ppm"))
    tan_is_current = current("nh3_ppm")
    if tan is not None:
        conditions = load_sample_conditions(conn, pond["id"], lab.get("sampled_at"), lab_cycle_id)
        assessment = assess_nh3(
            lookup, tan, conditions["sample_ph"], conditions["sample_temp_c"],
            conditions["sample_salinity_ppt"],
        )
        alert_value = assessment["nh3_unionized_ppm"]
        beyond_table = assessment["nh3_outside_handbook"]
        emerson = assessment["nh3_emerson_ppm"]
        temp_used = assessment["nh3_temp_adjusted"]
        salinity_used = assessment["nh3_salinity_adjusted"]
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE shrimp.lab_tests SET nh3_unionized_ppm = %s WHERE id = %s",
                (alert_value, lab["id"]),
            )
        if tan_is_current:
            if alert_value is None:
                extra = _nh3_note(False, False, True, emerson) if beyond_table else ("", "")
                handle("NH3_OUT_OF_RANGE", True, None, extra)
                resolve_alert(conn, pond["id"], "NH3_WARN")
                resolve_alert(conn, pond["id"], "NH3_DANGER")
            else:
                handle("NH3_OUT_OF_RANGE", False, None)
                note_vi, note_zh = _nh3_note(temp_used, salinity_used, False, None)
                danger = rules.get("NH3_DANGER")
                warn = rules.get("NH3_WARN")
                pct = water_change_pct(cycle if cycle else {"stage": stage})
                change = (f" Nên thay nước {pct}%.{note_vi}", f" 建議換水 {pct}%。{note_zh}")
                plain = (note_vi, note_zh)
                if danger:
                    firing = alert_value >= _num(danger["max_value"])
                    handle("NH3_DANGER", firing, alert_value, change if firing else plain)
                if warn:
                    firing = alert_value >= _num(warn["max_value"]) and not (
                        danger and alert_value >= _num(danger["max_value"])
                    )
                    handle("NH3_WARN", firing, alert_value, plain)

    potassium = _num(lab.get("k_ppm")) if current("k_ppm") else None
    if potassium is not None and rules.get("K_LOW"):
        handle("K_LOW", potassium < _num(rules["K_LOW"]["min_value"]), potassium)


def reevaluate_tan_for_probe(conn, reading) -> None:
    # A backfilled pH, DO temperature or salinity can change a historical sample.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.lab_tests
            WHERE pond_id = %s AND cycle_id IS NOT DISTINCT FROM %s
              AND nh3_ppm IS NOT NULL
              AND sampled_at >= %s
              AND sampled_at <= %s + interval '60 minutes'
              AND sampled_at <= now() + interval '5 minutes'
            """,
            (reading["pond_id"], reading.get("cycle_id"),
             reading["recorded_at"], reading["recorded_at"]),
        )
        rows = [dict(row) for row in cur.fetchall()]
    for lab in rows:
        evaluate_lab_test(conn, lab)


def reevaluate_latest_mineral_tests(conn, pond_id, cycle_id) -> None:
    reevaluate_latest_lab_tests(conn, pond_id, cycle_id, fields=("ca_ppm", "mg_ppm"))


def reevaluate_latest_lab_tests(conn, pond_id, cycle_id, fields=None) -> None:
    if fields is None:
        fields = ("no2_ppm", "nh3_ppm", "alkalinity_ppm", "ca_ppm", "mg_ppm", "k_ppm")
    latest_rows = {}
    with conn.cursor() as cur:
        for field in fields:
            cur.execute(
                f"""
                SELECT * FROM shrimp.lab_tests
                WHERE pond_id = %s AND cycle_id IS NOT DISTINCT FROM %s AND {field} IS NOT NULL
                  AND sampled_at <= now() + interval '5 minutes'
                ORDER BY sampled_at DESC, created_at DESC, id DESC
                LIMIT 1
                """,
                (pond_id, cycle_id),
            )
            row = cur.fetchone()
            if row:
                latest_rows[row["id"]] = dict(row)
    for lab in latest_rows.values():
        evaluate_lab_test(conn, lab)


def evaluate_stale_devices(conn) -> None:
    rules = load_rules(conn)
    rule = rules.get("DEVICE_STALE")
    if not rule:
        return
    minutes = _num(rule.get("max_value")) or STALE_DEFAULT_MINUTES
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.*, p.farmer_id, p.code, p.name, p.pond_type, p.id AS pond_uuid
            FROM shrimp.devices d
            JOIN shrimp.ponds p ON p.id = d.pond_id
            WHERE d.is_active = true AND d.pond_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM shrimp.probe_readings pr
                  WHERE pr.device_id = d.id
                    AND pr.pond_id = d.pond_id
                    AND pr.recorded_at >= now() - (%s || ' minutes')::interval
                    AND pr.recorded_at <= now() + interval '5 minutes'
              )
            """,
            (str(int(minutes)),),
        )
        stale = cur.fetchall()
        cur.execute(
            """
            SELECT pond_id FROM shrimp.alert_events
            WHERE rule_code = 'DEVICE_STALE' AND resolved_at IS NULL
            """
        )
        open_ponds = [r["pond_id"] for r in cur.fetchall()]
    stale_ponds = {r["pond_id"] for r in stale}
    for pond_id in open_ponds:
        if pond_id not in stale_ponds:
            resolve_alert(conn, pond_id, "DEVICE_STALE")
    for pond_id in stale_ponds:
        pond = load_pond(conn, pond_id)
        cycle = load_active_cycle(conn, pond_id)
        vi, zh = _msg("DEVICE_STALE", minutes, threshold=minutes)
        upsert_alert(conn, pond, cycle, rule, minutes, vi, zh)


def process_pending_readings(conn, limit: int = 100) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM shrimp.probe_readings
            WHERE alerts_evaluated_at IS NULL
            ORDER BY ingested_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for reading in rows:
        evaluate_probe_reading(conn, reading)
    return len(rows)
