"""Evaluate handbook thresholds and send notifications."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from access import farmer_ids_for_salesperson
from email_service import send_email
from telegram_service import send_message

NOTIFY_COOLDOWN = timedelta(hours=2)
STALE_DEFAULT_MINUTES = 60


def _num(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _doc_days(cycle: dict | None) -> int | None:
    if not cycle or not cycle.get("stocked_at"):
        return None
    stocked = cycle["stocked_at"]
    if isinstance(stocked, datetime):
        stocked = stocked.date()
    return (date.today() - stocked).days


def uses_10g_thresholds(cycle: dict | None) -> bool:
    if not cycle:
        return False
    weight = _num(cycle.get("sample_avg_weight_g"))
    if weight is not None and weight >= 10:
        return True
    doc = _doc_days(cycle)
    return cycle.get("stage") == "growout" and doc is not None and doc >= 35


def water_change_pct(cycle: dict | None) -> int:
    if cycle and cycle.get("stage") == "nursery":
        return 20
    return 40


def interpolate_nh3(lookup: list[dict], tan: float, ph: float) -> float | None:
    """Bilinear interpolation on handbook TAN x pH table."""
    if tan <= 0:
        return 0.0
    tans = sorted({float(r["tan_ppm"]) for r in lookup})
    phs = sorted({float(r["ph"]) for r in lookup})
    grid = {(float(r["tan_ppm"]), float(r["ph"])): float(r["nh3_ppm"]) for r in lookup}

    def clamp_pair(values, x):
        if x <= values[0]:
            return values[0], values[0]
        if x >= values[-1]:
            return values[-1], values[-1]
        for i in range(len(values) - 1):
            if values[i] <= x <= values[i + 1]:
                return values[i], values[i + 1]
        return values[-1], values[-1]

    t0, t1 = clamp_pair(tans, tan)
    p0, p1 = clamp_pair(phs, ph)
    q00 = grid[(t0, p0)]
    q01 = grid[(t0, p1)]
    q10 = grid[(t1, p0)]
    q11 = grid[(t1, p1)]
    td = 0.0 if t1 == t0 else (tan - t0) / (t1 - t0)
    pd = 0.0 if p1 == p0 else (ph - p0) / (p1 - p0)
    return (q00 * (1 - td) * (1 - pd) + q10 * td * (1 - pd) + q01 * (1 - td) * pd + q11 * td * pd)


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


def notify_alert(conn, event: dict, pond: dict) -> None:
    people = recipients_for_pond(conn, pond, event["severity"])
    subject = f"[Uni-Shrimp] {event['rule_code']} · {pond.get('code')}"
    for person in people:
        locale = person.get("locale") or "vi"
        body = event["message_vi"] if locale == "vi" else event["message_zh"]
        text = f"{pond.get('code')} {pond.get('name')}\n{body}"
        html = f"<p><b>{pond.get('code')}</b> {pond.get('name')}</p><p>{body}</p>"
        ok, err = send_email(person.get("email"), subject, html)
        _log_notification(conn, event["id"], person["id"], "email", ok, err)
        tok, terr = send_message(person.get("telegram_chat_id"), text)
        _log_notification(conn, event["id"], person["id"], "telegram", tok, terr)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE shrimp.alert_events
            SET last_notified_at = now(), notify_count = notify_count + 1
            WHERE id = %s
            """,
            (event["id"],),
        )


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
                notify_alert(conn, event, pond)
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
    notify_alert(conn, event, pond)


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
    shown = f"{value:.2f}" if isinstance(value, (int, float, Decimal)) else str(value)
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
        "NO2_HARVEST_EARLY": f"NO₂ ≥ {limit} ppm liên tục 7 ngày. Nên thu tỉa sớm.",
        "NH3_WARN": f"NH₃ không ion hóa {shown} ppm (cảnh báo).",
        "NH3_DANGER": f"NH₃ không ion hóa {shown} ppm (độc hại).",
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
        "NO2_HARVEST_EARLY": f"NO₂ 連續 7 天 ≥ {limit} ppm，建議提前收成。",
        "NH3_WARN": f"未電離 NH₃ {shown} ppm（警告）。",
        "NH3_DANGER": f"未電離 NH₃ {shown} ppm（有害）。",
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
            if code.startswith("PH") or code.startswith("NH3"):
                pct = water_change_pct(cycle)
                extra_vi = f" Nên thay nước {pct}%."
                extra_zh = f" 建議換水 {pct}%。"
            threshold = rule.get("min_value" if "LOW" in code or code == "DO_CRITICAL" else "max_value")
            vi, zh = _msg(code, value, extra_vi, extra_zh, threshold)
            upsert_alert(conn, pond, cycle, rule, value, vi, zh)
        else:
            resolve_alert(conn, pond["id"], code)

    if ph is not None:
        handle("PH_LOW", ph < _num(rules.get("PH_LOW", {}).get("min_value")) if rules.get("PH_LOW") else False, ph)
        handle("PH_HIGH", ph > _num(rules.get("PH_HIGH", {}).get("max_value")) if rules.get("PH_HIGH") else False, ph)
    if do_v is not None:
        crit = rules.get("DO_CRITICAL")
        low = rules.get("DO_LOW")
        handle("DO_CRITICAL", bool(crit) and do_v < _num(crit["min_value"]), do_v)
        handle("DO_LOW", bool(low) and do_v < _num(low["min_value"]) and not (crit and do_v < _num(crit["min_value"])), do_v)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shrimp.probe_readings SET alerts_evaluated_at = now() WHERE id = %s",
            (reading["id"],),
        )


def _latest_ph(conn, pond_id) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ph FROM shrimp.probe_readings
            WHERE pond_id = %s AND ph IS NOT NULL
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (pond_id,),
        )
        row = cur.fetchone()
        return _num(row["ph"]) if row else None


def consecutive_no2_days(conn, pond_id, threshold: float) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT sampled_at::date AS d, max(no2_ppm) AS no2
            FROM shrimp.lab_tests
            WHERE pond_id = %s AND no2_ppm IS NOT NULL
            GROUP BY sampled_at::date
            ORDER BY d DESC
            LIMIT 14
            """,
            (pond_id,),
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
        if _num(row["no2"]) >= threshold:
            streak += 1
            expected = expected - timedelta(days=1)
        else:
            break
    return streak


def evaluate_lab_test(conn, lab: dict) -> None:
    pond = load_pond(conn, lab["pond_id"])
    if not pond:
        return
    cycle = load_active_cycle(conn, pond["id"])
    rules = load_rules(conn)
    lookup = load_lookup(conn)
    stage = (cycle or {}).get("stage") or ("nursery" if pond["pond_type"] == "nursery" else "growout")
    big = uses_10g_thresholds(cycle)
    pct = water_change_pct(cycle if cycle else {"stage": stage})
    extra_vi = f" Nên thay nước {pct}%."
    extra_zh = f" 建議換水 {pct}%。"

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

    alk = _num(lab.get("alkalinity_ppm"))
    if alk is not None and rules.get("ALK_LOW"):
        handle("ALK_LOW", alk < _num(rules["ALK_LOW"]["min_value"]), alk)

    ca = _num(lab.get("ca_ppm"))
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

    mg = _num(lab.get("mg_ppm"))
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

    no2 = _num(lab.get("no2_ppm"))
    if no2 is not None and rules.get("NO2_HIGH"):
        handle("NO2_HIGH", no2 >= _num(rules["NO2_HIGH"]["max_value"]), no2, (extra_vi, extra_zh))
    if no2 is not None and rules.get("NO2_HARVEST_EARLY"):
        streak = consecutive_no2_days(conn, pond["id"], _num(rules["NO2_HARVEST_EARLY"]["max_value"]))
        handle("NO2_HARVEST_EARLY", streak >= 7, no2)

    tan = _num(lab.get("nh3_ppm"))
    ph = _latest_ph(conn, pond["id"])
    unionized = None
    if tan is not None and ph is not None and lookup:
        unionized = interpolate_nh3(lookup, tan, ph)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE shrimp.lab_tests SET nh3_unionized_ppm = %s WHERE id = %s",
                (unionized, lab["id"]),
            )
        danger = rules.get("NH3_DANGER")
        warn = rules.get("NH3_WARN")
        if danger:
            handle("NH3_DANGER", unionized >= _num(danger["max_value"]), unionized, (extra_vi, extra_zh))
        if warn:
            firing = unionized >= _num(warn["max_value"]) and not (
                danger and unionized >= _num(danger["max_value"])
            )
            handle("NH3_WARN", firing, unionized, (extra_vi, extra_zh))


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
              AND (d.last_seen_at IS NULL OR d.last_seen_at < now() - (%s || ' minutes')::interval)
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
