"""Fourth-review regressions; database changes roll back and notifications are mocked."""
from test_third_review import RULES, farm, lab, probe, open_codes
import pytest
from datetime import timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
import alerts
from models import CycleUpdate
from routers.ponds import update_cycle

class Uncommitted:
    def __init__(self, conn): self.conn = conn
    def cursor(self, *a, **kw): return self.conn.cursor(*a, **kw)
    def commit(self): pass

@pytest.mark.parametrize("db_timezone", ["UTC", "Asia/Ho_Chi_Minh", "America/New_York"])
def test_no2_uses_farm_days(farm, db_timezone):
    conn, pond, cycle, now = farm
    with conn.cursor() as cur:
        cur.execute("SET LOCAL TIME ZONE %s", (db_timezone,))
    start = now.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=8)
    for day in range(7):
        when = start + timedelta(days=day)
        if day == 3: when = when.replace(hour=6)
        lab(conn, pond, cycle, when, no2_ppm=8)
    assert alerts.consecutive_no2_days(conn, pond['id'], 7, cycle['id']) == 7

def test_late_ph_recalculates_tan(farm):
    conn, pond, cycle, now = farm
    sample = lab(conn, pond, cycle, now, nh3_ppm=1)
    alerts.evaluate_lab_test(conn, sample)
    reading = probe(conn, pond, cycle, now - timedelta(minutes=5), 8)
    alerts.evaluate_probe_reading(conn, reading)
    with conn.cursor() as cur:
        cur.execute('SELECT nh3_unionized_ppm FROM shrimp.lab_tests WHERE id=%s', (sample['id'],))
        assert cur.fetchone()['nh3_unionized_ppm'] is not None

def test_reactivate_restores_lab_alert(farm):
    conn, pond, cycle, now = farm
    sample = lab(conn, pond, cycle, now, ca_ppm=50)
    alerts.evaluate_lab_test(conn, sample)
    user = {'role':'admin', 'id':str(pond['farmer_id'])}
    update_cycle(cycle['id'], CycleUpdate(status='harvested'), user, Uncommitted(conn))
    update_cycle(cycle['id'], CycleUpdate(status='active'), user, Uncommitted(conn))
    assert 'CA_LOW_GROWOUT' in open_codes(conn, pond)


def test_late_ph_switches_unknown_to_danger_without_using_other_cycle(farm):
    conn, pond, cycle, now = farm
    rules = RULES | {
        "NH3_OUT_OF_RANGE": {"code": "NH3_OUT_OF_RANGE", "metric": "nh3_ppm", "severity": "warn"},
        "NH3_DANGER": {"code": "NH3_DANGER", "metric": "nh3_ppm", "max_value": 0.001, "severity": "critical"},
    }
    with patch.object(alerts, "load_rules", return_value=rules):
        sample = lab(conn, pond, cycle, now, nh3_ppm=1)
        alerts.evaluate_lab_test(conn, sample)
        assert "NH3_OUT_OF_RANGE" in open_codes(conn, pond)
        foreign = probe(conn, pond, {"id": None}, now - timedelta(minutes=5), 8)
        alerts.evaluate_probe_reading(conn, foreign)
        assert "NH3_OUT_OF_RANGE" in open_codes(conn, pond)
        too_old = probe(conn, pond, cycle, now - timedelta(minutes=61), 8)
        alerts.evaluate_probe_reading(conn, too_old)
        assert "NH3_OUT_OF_RANGE" in open_codes(conn, pond)
        # This pH is not the pond's newest reading, but is the sample's valid match.
        probe(conn, pond, cycle, now + timedelta(minutes=1), 7.7)
        valid = probe(conn, pond, cycle, now - timedelta(minutes=5), 8)
        alerts.evaluate_probe_reading(conn, valid)
        assert "NH3_OUT_OF_RANGE" not in open_codes(conn, pond)
        assert "NH3_DANGER" in open_codes(conn, pond)


def test_reactivate_evaluates_each_latest_metric(farm):
    conn, pond, cycle, now = farm
    rules = RULES | {
        "K_LOW": {"code": "K_LOW", "metric": "k_ppm", "min_value": 150, "severity": "warn"},
        "ALK_LOW": {"code": "ALK_LOW", "metric": "alkalinity_ppm", "min_value": 150, "severity": "warn"},
    }
    with patch.object(alerts, "load_rules", return_value=rules):
        for age, values in enumerate(({"ca_ppm": 50}, {"k_ppm": 50}, {"alkalinity_ppm": 50})):
            sample = lab(conn, pond, cycle, now - timedelta(minutes=age), **values)
            alerts.evaluate_lab_test(conn, sample)
        user = {"role": "admin", "id": str(pond["farmer_id"])}
        update_cycle(cycle["id"], CycleUpdate(status="harvested"), user, Uncommitted(conn))
        assert not open_codes(conn, pond)
        update_cycle(cycle["id"], CycleUpdate(status="active"), user, Uncommitted(conn))
        assert open_codes(conn, pond) == {"CA_LOW_GROWOUT", "K_LOW", "ALK_LOW"}
