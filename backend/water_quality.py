"""Derived water-quality figures. Probe raw values are never rewritten.

Unionized ammonia uses Emerson et al. (1975) for the freshwater pKa.
When salinity is present, Whitfield's ionic-strength shift is applied
(pKa increases slightly, so the NH3 fraction falls). The handbook TAN x pH
table remains the range gate; this formula does not replace it.

Dissolved-oxygen solubility uses the Garcia and Gordon (1992) fit to the
Benson and Krause (1984) measurements, converted from mL/L to mg/L by the
USGS factor 1.42905, at a sea-level pressure of 1013.25 mbar.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FARM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MORNING_HOURS = (5, 7)
AFTERNOON_HOURS = (13, 16)
MAX_WINDOW_GAP = timedelta(minutes=90)
SATURATION_SUSPECT_POINTS = 15.0
MAX_AMMONIA_SALINITY_PPT = 45.0
ML_TO_MG = 1.42905
SEA_LEVEL_MBAR = 1013.25
MMHG_PER_MBAR = 0.750061683


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def handbook_upper_bounds(lookup: list[dict]) -> tuple[float, float] | None:
    if not lookup:
        return None
    tans = [float(row["tan_ppm"]) for row in lookup]
    phs = [float(row["ph"]) for row in lookup]
    return max(tans), max(phs)


def outside_handbook(lookup: list[dict], tan, ph) -> bool:
    bounds = handbook_upper_bounds(lookup)
    tan_n, ph_n = _num(tan), _num(ph)
    if bounds is None or tan_n is None or ph_n is None:
        return False
    return tan_n > bounds[0] or ph_n > bounds[1]


def salinity_for_ammonia(salinity_ppt) -> float | None:
    """Salinity used for the pKa shift. Implausible probe values are ignored."""
    salinity = _num(salinity_ppt)
    if salinity is None or salinity <= 0 or salinity > MAX_AMMONIA_SALINITY_PPT:
        return None
    return salinity


def ammonia_pka(temp_c: float, salinity_ppt: float | None = None) -> float | None:
    """pKa of NH4+. None when temperature is outside 0-40 C.

    Salinity above 45 ppt is ignored. The ionic-strength term is only meaningful
    for seawater-like ponds, and higher values make the denominator zero.
    """
    if temp_c < 0 or temp_c > 40:
        return None
    pka = 0.09018 + 2729.92 / (temp_c + 273.15)
    salinity = salinity_for_ammonia(salinity_ppt)
    if salinity is not None:
        denominator = 1000.0 - 1.005109 * salinity
        if denominator <= 0:
            return pka
        ionic = 19.9273 * salinity / denominator
        pka += (0.1552 - 0.0003142 * temp_c) * ionic
    return pka


def unionized_nh3_ppm(tan_ppm, ph, temp_c, salinity_ppt=None) -> float | None:
    tan = _num(tan_ppm)
    acidity = _num(ph)
    temperature = _num(temp_c)
    if tan is None or acidity is None or temperature is None or tan < 0:
        return None
    if tan == 0:
        return 0.0
    pka = ammonia_pka(temperature, salinity_ppt)
    if pka is None:
        return None
    fraction = 1.0 / (1.0 + 10 ** (pka - acidity))
    return tan * fraction


def oxygen_solubility_mg_l(temp_c, salinity_ppt=None) -> float | None:
    """Air-saturated dissolved oxygen at sea level, mg/L."""
    temperature = _num(temp_c)
    if temperature is None or temperature <= 0 or temperature >= 40:
        return None
    salinity = _num(salinity_ppt) or 0.0
    if salinity < 0 or salinity > 80:
        return None
    vapor_mmhg = 10 ** (8.10765 - 1750.286 / (235 + temperature))
    pressure = (SEA_LEVEL_MBAR * MMHG_PER_MBAR - vapor_mmhg) / (760 - vapor_mmhg)
    ts = math.log((298.15 - temperature) / (273.15 + temperature))
    ln_c = (
        2.00907
        + 3.22014 * ts
        + 4.05010 * ts ** 2
        + 4.94457 * ts ** 3
        - 2.56847e-1 * ts ** 4
        + 3.88767 * ts ** 5
        - salinity * (
            6.24523e-3
            + 7.37614e-3 * ts
            + 1.03410e-2 * ts ** 2
            + 8.17083e-3 * ts ** 3
        )
        - 4.88682e-7 * salinity ** 2
    )
    return math.exp(ln_c) * ML_TO_MG * pressure


def theoretical_do_sat_pct(do_mg_l, temp_c, salinity_ppt=None) -> float | None:
    dissolved = _num(do_mg_l)
    solubility = oxygen_solubility_mg_l(temp_c, salinity_ppt)
    if dissolved is None or solubility is None or solubility <= 0 or dissolved < 0:
        return None
    return 100.0 * dissolved / solubility


def probe_saturation_suspect(probe_pct, theoretical_pct) -> bool:
    probe = _num(probe_pct)
    theoretical = _num(theoretical_pct)
    if probe is None or theoretical is None:
        return False
    return abs(probe - theoretical) >= SATURATION_SUSPECT_POINTS


def annotate_probe(reading: dict | None) -> dict | None:
    if not reading:
        return reading
    theoretical = theoretical_do_sat_pct(
        reading.get("do_mg_l"),
        reading.get("temp_c") if reading.get("temp_c") is not None else reading.get("do_temp_c"),
        reading.get("salinity_ppt"),
    )
    reading["do_sat_theoretical_pct"] = None if theoretical is None else round(theoretical, 1)
    reading["do_sat_probe_suspect"] = probe_saturation_suspect(reading.get("do_sat_pct"), theoretical)
    reading["do_sat_salinity_used"] = _num(reading.get("salinity_ppt")) is not None
    return reading


def _local_time(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(FARM_TZ)


def _window_ok(points) -> bool:
    if len(points) < 2:
        return False
    times = sorted(point[0] for point in points)
    return all(b - a <= MAX_WINDOW_GAP for a, b in zip(times, times[1:]))


def _mean(points, index) -> float | None:
    values = [point[index] for point in points if point[index] is not None]
    if len(values) < 2:
        return None
    return sum(values) / len(values)


def diurnal_swing(readings, on_date=None) -> dict | None:
    """Afternoon minus morning means. None when either window is too thin or gappy."""
    points = []
    for row in readings or []:
        if not isinstance(row, dict):
            return None
        local = _local_time(row.get("recorded_at"))
        if local is None:
            continue
        points.append((local, _num(row.get("ph")), _num(row.get("do_mg_l"))))
    day = on_date or datetime.now(FARM_TZ).date()
    points = [point for point in points if point[0].date() == day]
    morning = [point for point in points if MORNING_HOURS[0] <= point[0].hour < MORNING_HOURS[1]]
    afternoon = [point for point in points if AFTERNOON_HOURS[0] <= point[0].hour < AFTERNOON_HOURS[1]]
    if not _window_ok(morning) or not _window_ok(afternoon):
        return None
    result = {}
    ph_morning, ph_afternoon = _mean(morning, 1), _mean(afternoon, 1)
    do_morning, do_afternoon = _mean(morning, 2), _mean(afternoon, 2)
    if ph_morning is not None and ph_afternoon is not None:
        result["delta_ph"] = round(ph_afternoon - ph_morning, 2)
    if do_morning is not None and do_afternoon is not None:
        result["delta_do"] = round(do_afternoon - do_morning, 2)
    return result or None
