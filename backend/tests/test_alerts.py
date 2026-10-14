from alerts import interpolate_nh3, uses_10g_thresholds, water_change_pct


LOOKUP = [
    {"tan_ppm": 0.25, "ph": 7.6, "nh3_ppm": 0.01},
    {"tan_ppm": 0.25, "ph": 7.8, "nh3_ppm": 0.01},
    {"tan_ppm": 1.0, "ph": 7.6, "nh3_ppm": 0.02},
    {"tan_ppm": 1.0, "ph": 7.8, "nh3_ppm": 0.04},
    {"tan_ppm": 10.0, "ph": 9.0, "nh3_ppm": 3.61},
]


def test_interpolate_exact():
    assert interpolate_nh3(LOOKUP, 10.0, 9.0) == 3.61


def test_interpolate_below_table_uses_lowest_cell():
    low = interpolate_nh3(LOOKUP, 0.1, 6.5)
    edge = interpolate_nh3(LOOKUP, 0.25, 7.6)
    assert low == edge
    assert interpolate_nh3(LOOKUP, 0, 8) == 0.0


def test_10g_by_weight():
    assert uses_10g_thresholds({"sample_avg_weight_g": 10, "stage": "growout", "stocked_at": None})


def test_water_change():
    assert water_change_pct({"stage": "nursery"}) == 20
    assert water_change_pct({"stage": "growout"}) == 40
