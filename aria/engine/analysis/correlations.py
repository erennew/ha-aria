"""Pearson correlation and cross-metric correlation discovery."""

import logging
import math
import os

logger = logging.getLogger(__name__)

# EV vehicle key in snapshot["ev"] dict.
# Override via ARIA_EV_NAME env var if your vehicle is named differently.
# Matches the key written by aria.engine.collectors.extractors (default: "TARS").
EV_NAME = os.environ.get("ARIA_EV_NAME", "TARS")


def pearson_r(x, y):
    """Compute Pearson correlation coefficient between two sequences."""
    n = len(x)
    if n < 3 or n != len(y):
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=True))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _safe_get(snap, *keys):
    """Navigate a nested dict via keys, returning None if any key is missing."""
    obj = snap
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
        if obj is None:
            return None
    return obj


def cross_correlate(snapshots, min_r=0.5):
    """Find significant correlations between all tracked metrics."""
    if len(snapshots) < 5:
        return []

    series = {
        "weather_temp": [],
        "calendar_count": [],
        "is_weekend": [],
        "power_watts": [],
        "lights_on": [],
        "devices_home": [],
        "unavailable": [],
        "useful_events": [],
        "ev_battery": [],
        "ev_power": [],
    }

    for snap in snapshots:
        snap_id = snap.get("date", snap.get("id", "unknown"))

        series["weather_temp"].append(snap.get("weather", {}).get("temp_f") or 0)
        series["calendar_count"].append(len(snap.get("calendar_events", [])))
        series["is_weekend"].append(1 if snap.get("is_weekend") else 0)

        power_watts = _safe_get(snap, "power", "total_watts")
        if power_watts is None:
            logger.warning("cross_correlate: snapshot missing 'power.total_watts' — snap: %s", snap_id)
            power_watts = 0
        series["power_watts"].append(power_watts)

        lights_on = _safe_get(snap, "lights", "on")
        if lights_on is None:
            logger.warning("cross_correlate: snapshot missing 'lights.on' — snap: %s", snap_id)
            lights_on = 0
        series["lights_on"].append(lights_on)

        devices_home = _safe_get(snap, "occupancy", "device_count_home")
        if devices_home is None:
            logger.warning(
                "cross_correlate: snapshot missing 'occupancy.device_count_home' — snap: %s",
                snap_id,
            )
            devices_home = 0
        series["devices_home"].append(devices_home)

        unavailable = _safe_get(snap, "entities", "unavailable")
        if unavailable is None:
            logger.warning("cross_correlate: snapshot missing 'entities.unavailable' — snap: %s", snap_id)
            unavailable = 0
        series["unavailable"].append(unavailable)

        series["useful_events"].append(snap.get("logbook_summary", {}).get("useful_events", 0))

        ev = snap.get("ev", {}).get(EV_NAME, {})
        series["ev_battery"].append(ev.get("battery_pct", 0))
        series["ev_power"].append(ev.get("charger_power_kw", 0))

    keys = list(series.keys())
    results = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            r = pearson_r(series[keys[i]], series[keys[j]])
            if abs(r) >= min_r:
                strength = "strong" if abs(r) >= 0.8 else "moderate"
                direction = "positive" if r > 0 else "negative"
                results.append(
                    {
                        "x": keys[i],
                        "y": keys[j],
                        "r": round(r, 3),
                        "strength": strength,
                        "direction": direction,
                        "description": f"{keys[i]} ↔ {keys[j]}: r={r:.2f} ({strength} {direction})",
                    }
                )

    results.sort(key=lambda c: -abs(c["r"]))
    return results
