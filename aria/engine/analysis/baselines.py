"""Compute per-day-of-week baselines from historical snapshots."""

import logging
import statistics

logger = logging.getLogger(__name__)

# Minimum top-level keys required to treat a snapshot as complete enough to baseline.
# Snapshots missing any of these keys produce a malformed baseline with all-zero metrics.
REQUIRED_BASELINE_KEYS = {"power", "lights", "occupancy"}

# (metric_name, top_key, sub_key) for guarded extraction
_METRIC_PATHS = [
    ("power_watts", "power", "total_watts"),
    ("lights_on", "lights", "on"),
    ("lights_off", "lights", "off"),
    ("devices_home", "occupancy", "device_count_home"),
    ("unavailable", "entities", "unavailable"),
]


def _extract_metric_values(snaps):
    """Extract metric values from snapshots, logging warnings for missing keys.

    Returns a dict of metric_name -> list of float values.
    Snapshots missing required keys are skipped per metric with a WARNING.
    """
    result = {name: [] for name, _, _ in _METRIC_PATHS}
    result["useful_events"] = []

    for s in snaps:
        snap_id = s.get("date", s.get("id", "unknown"))

        for metric, top_key, sub_key in _METRIC_PATHS:
            top = s.get(top_key)
            if top is None or top.get(sub_key) is None:
                logger.warning(
                    "compute_baselines: snapshot missing '%s.%s' — snap: %s",
                    top_key,
                    sub_key,
                    snap_id,
                )
            else:
                result[metric].append(top[sub_key])

        result["useful_events"].append(s.get("logbook_summary", {}).get("useful_events", 0))

    return result


def compute_baselines(snapshots):
    """Compute per-day-of-week baselines from historical snapshots."""
    by_day = {}
    for snap in snapshots:
        missing_keys = REQUIRED_BASELINE_KEYS - snap.keys()
        if missing_keys:
            snap_id = snap.get("date", snap.get("id", "unknown"))
            logger.warning(
                "baselines: skipping partial snapshot — missing keys: %s — snap: %s",
                missing_keys,
                snap_id,
            )
            continue
        dow = snap.get("day_of_week", "Unknown")
        by_day.setdefault(dow, []).append(snap)

    baselines = {}
    for dow, snaps in by_day.items():
        metrics = _extract_metric_values(snaps)

        baseline = {"sample_count": len(snaps)}
        for metric_name, values in metrics.items():
            if len(values) >= 2:
                baseline[metric_name] = {
                    "mean": statistics.mean(values),
                    "stddev": statistics.stdev(values),
                    "min": min(values),
                    "max": max(values),
                }
            elif len(values) == 1:
                baseline[metric_name] = {
                    "mean": values[0],
                    "stddev": 0,
                    "min": values[0],
                    "max": values[0],
                }
        baselines[dow] = baseline

    return baselines
