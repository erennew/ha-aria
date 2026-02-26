"""Z-score anomaly detection against day-of-week baselines."""

import logging

logger = logging.getLogger(__name__)

ANOMALY_THRESHOLD = 2.0  # z-score above which we flag anomaly

# Mapping from metric name to (top-level key, sub-key) for safe extraction
_METRIC_KEYS = {
    "power_watts": ("power", "total_watts"),
    "lights_on": ("lights", "on"),
    "devices_home": ("occupancy", "device_count_home"),
    "unavailable": ("entities", "unavailable"),
}


def _extract_current_values(snapshot):
    """Extract all current metric values from a snapshot with null guards.

    Returns a values dict where metrics with missing snapshot keys are set to
    None (rather than aborting all detection). Callers must skip None entries.
    """
    snap_id = snapshot.get("date", snapshot.get("id", "unknown"))
    values = {}

    for metric, (top_key, sub_key) in _METRIC_KEYS.items():
        top = snapshot.get(top_key)
        if top is None:
            logger.warning("detect_anomalies: snapshot missing '%s' key — snap: %s", top_key, snap_id)
            values[metric] = None
            continue
        val = top.get(sub_key)
        if val is None:
            logger.warning(
                "detect_anomalies: snapshot missing '%s.%s' — snap: %s",
                top_key,
                sub_key,
                snap_id,
            )
            values[metric] = None
            continue
        values[metric] = val

    values["useful_events"] = snapshot.get("logbook_summary", {}).get("useful_events", 0)
    return values


def detect_anomalies(snapshot, baselines):
    """Detect z-score anomalies vs day-of-week baseline."""
    dow = snapshot.get("day_of_week", "Unknown")
    baseline = baselines.get(dow, {})
    if not baseline:
        return []

    current_values = _extract_current_values(snapshot)

    anomalies = []
    for metric, current in current_values.items():
        if current is None:
            continue
        bl = baseline.get(metric, {})
        mean = bl.get("mean")
        stddev = bl.get("stddev")
        if mean is None or stddev is None or stddev == 0:
            continue
        z = abs(current - mean) / stddev
        if z > ANOMALY_THRESHOLD:
            direction = "above" if current > mean else "below"
            anomalies.append(
                {
                    "metric": metric,
                    "current": current,
                    "mean": mean,
                    "stddev": stddev,
                    "z_score": round(z, 2),
                    "direction": direction,
                    "description": f"{metric} is {z:.1f}σ {direction} normal ({current} vs {mean:.0f}±{stddev:.0f})",
                }
            )

    return anomalies
