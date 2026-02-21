"""Environmental correlator — Pearson r between event times and sun/illuminance.

Determines whether a behavioral pattern tracks environmental conditions
(sunset, illuminance) rather than the clock. Used by the condition builder
to decide between time-based and sensor-based trigger conditions.
"""

import logging
import statistics
from datetime import datetime

logger = logging.getLogger(__name__)

ISO_FMT = "%Y-%m-%dT%H:%M:%S"
MIN_DATA_POINTS = 3  # Need at least 3 paired points for meaningful correlation


def _parse_ts(ts: str) -> datetime:
    """Parse ISO timestamp, truncating fractional seconds."""
    return datetime.strptime(ts[:19], ISO_FMT)


def _to_minutes(ts: str) -> float | None:
    """Convert ISO timestamp to minutes-since-midnight."""
    try:
        dt = _parse_ts(ts)
        return dt.hour * 60 + dt.minute + dt.second / 60
    except (ValueError, TypeError):
        return None


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient between two lists.

    Returns 0.0 if insufficient data or zero variance.
    """
    if len(xs) < MIN_DATA_POINTS or len(xs) != len(ys):
        return 0.0

    try:
        mean_x = statistics.mean(xs)
        mean_y = statistics.mean(ys)
        stdev_x = statistics.stdev(xs)
        stdev_y = statistics.stdev(ys)
    except statistics.StatisticsError:
        return 0.0

    if stdev_x == 0 or stdev_y == 0:
        return 0.0

    n = len(xs)
    covariance = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / (n - 1)
    return covariance / (stdev_x * stdev_y)


def _pair_by_date(
    event_timestamps: list[str],
    reference_events: list[dict],
    value_key: str | None = None,
) -> tuple[list[float], list[float]]:
    """Pair event times with reference values by matching date.

    For sun events: pairs event minute-of-day with sun-event minute-of-day.
    For illuminance events: pairs event minute-of-day with illuminance value.

    Returns two aligned lists of floats for correlation.
    """
    # Build date → event minute lookup
    event_by_date: dict[str, float] = {}
    for ts in event_timestamps:
        minutes = _to_minutes(ts)
        if minutes is None:
            continue
        date_key = ts[:10]
        # Take the first event per date
        if date_key not in event_by_date:
            event_by_date[date_key] = minutes

    # Build date → reference value lookup
    ref_by_date: dict[str, float] = {}
    for ref in reference_events:
        ref_ts = ref.get("timestamp", "")
        date_key = ref_ts[:10]
        if not date_key:
            continue
        if value_key:
            val = ref.get(value_key)
            if val is not None:
                ref_by_date.setdefault(date_key, float(val))
        else:
            minutes = _to_minutes(ref_ts)
            if minutes is not None:
                ref_by_date.setdefault(date_key, minutes)

    # Align by date
    common_dates = sorted(set(event_by_date) & set(ref_by_date))
    xs = [event_by_date[d] for d in common_dates]
    ys = [ref_by_date[d] for d in common_dates]
    return xs, ys


def correlate_with_environment(
    event_timestamps: list[str],
    sun_events: list[dict] | None = None,
    illuminance_events: list[dict] | None = None,
    threshold: float = 0.7,
) -> dict:
    """Compute correlation between event times and environmental signals.

    Args:
        event_timestamps: ISO 8601 timestamps of the behavioral events.
        sun_events: List of dicts with "timestamp" and "elevation" fields
            (e.g., sunset times from HA sun entity).
        illuminance_events: List of dicts with "timestamp" and "value" fields
            (e.g., lux readings from illuminance sensor).
        threshold: Minimum |r| to consider correlation significant.

    Returns:
        Dict with keys:
        - prefer_sun_trigger: bool — True if events track sun position
        - sun_correlation_r: float — Pearson r with sun times
        - prefer_illuminance_trigger: bool — True if events track illuminance
        - illuminance_correlation_r: float — Pearson r with illuminance values
    """
    result = {
        "prefer_sun_trigger": False,
        "sun_correlation_r": 0.0,
        "prefer_illuminance_trigger": False,
        "illuminance_correlation_r": 0.0,
    }

    if len(event_timestamps) < MIN_DATA_POINTS:
        return result

    # Sun correlation: event time-of-day vs sun event time-of-day
    if sun_events:
        xs, ys = _pair_by_date(event_timestamps, sun_events)
        r = _pearson_r(xs, ys)
        result["sun_correlation_r"] = round(r, 4)
        result["prefer_sun_trigger"] = abs(r) >= threshold

    # Illuminance correlation: event time-of-day vs illuminance time-of-day
    # If illuminance readings shift with the events, the behavior tracks light.
    if illuminance_events:
        xs, ys = _pair_by_date(event_timestamps, illuminance_events)
        r = _pearson_r(xs, ys)
        result["illuminance_correlation_r"] = round(r, 4)
        result["prefer_illuminance_trigger"] = abs(r) >= threshold

    return result
