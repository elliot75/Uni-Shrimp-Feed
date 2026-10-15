from datetime import datetime, timedelta, timezone

from water_quality import (
    diurnal_swing,
    oxygen_solubility_mg_l,
    probe_saturation_suspect,
    theoretical_do_sat_pct,
    unionized_nh3_ppm,
)


def test_freshwater_oxygen_matches_standard_20c():
    assert abs(oxygen_solubility_mg_l(20, 0) - 9.09) < 0.02


def test_example_probe_saturation_is_not_under_one_percent():
    percent = theoretical_do_sat_pct(5.62, 26.08, 15.84)
    assert 70 < percent < 80
    assert probe_saturation_suspect(0.7, percent)
    assert not probe_saturation_suspect(74, percent)


def test_emerson_freshwater_fraction_at_25c_ph8():
    # 1 mg/L TAN, freshwater: about 5.4% un-ionized.
    assert abs(unionized_nh3_ppm(1, 8, 25, 0) - 0.0537) < 0.002


def test_extreme_salinity_is_ignored_instead_of_raising():
    fresh = unionized_nh3_ppm(1, 8.74, 26, None)
    assert unionized_nh3_ppm(1, 8.74, 26, 999) == fresh
    assert unionized_nh3_ppm(1, 8.74, 26, 2000) == fresh


def test_salinity_lowers_unionized_fraction():
    fresh = unionized_nh3_ppm(1, 8.74, 26, None)
    salty = unionized_nh3_ppm(1, 8.74, 26, 15.84)
    assert 0.20 < fresh < 0.30
    assert salty < fresh


def test_temperature_outside_range_is_not_adjusted():
    assert unionized_nh3_ppm(1, 8, 45, 15) is None


def test_diurnal_swing_requires_dense_windows():
    from zoneinfo import ZoneInfo
    morning = datetime(2026, 10, 13, 22, 30, tzinfo=timezone.utc)
    afternoon = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
    vietnam_day = morning.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    readings = [
        {"recorded_at": morning, "ph": 7.6, "do_mg_l": 4.0},
        {"recorded_at": morning + timedelta(minutes=30), "ph": 7.7, "do_mg_l": 4.2},
        {"recorded_at": afternoon, "ph": 8.1, "do_mg_l": 6.0},
        {"recorded_at": afternoon + timedelta(minutes=30), "ph": 8.2, "do_mg_l": 6.2},
    ]
    swing = diurnal_swing(readings, on_date=vietnam_day)
    assert swing["delta_ph"] == 0.5
    assert swing["delta_do"] == 2.0
    assert diurnal_swing(readings[:3], on_date=vietnam_day) is None
