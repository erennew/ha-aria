"""Device reliability scoring from historical snapshot data."""

import logging

logger = logging.getLogger(__name__)


def compute_device_reliability(snapshots):
    """Compute reliability score per device from historical snapshots.

    Score = 100 * (days_available / total_days). Tracks trend direction.
    Only reports devices that were unavailable at least once.
    """
    device_outages = {}
    total_days = len(snapshots)
    if total_days == 0:
        return {}

    for snap in snapshots:
        unavail_list = snap.get("entities", {}).get("unavailable_list", [])
        date = snap.get("date")
        if date is None:
            logger.warning("compute_device_reliability: snapshot missing 'date' key — skipping snap")
            continue
        for eid in unavail_list:
            device_outages.setdefault(eid, []).append(date)

    scores = {}
    for eid, outage_dates in device_outages.items():
        outage_days = len(outage_dates)
        score = round(100 * (1 - outage_days / total_days))
        mid = total_days // 2
        early_dates = set(s.get("date") for s in snapshots[:mid] if s.get("date") is not None)
        late_dates = set(s.get("date") for s in snapshots[mid:] if s.get("date") is not None)
        early_outages = len([d for d in outage_dates if d in early_dates])
        late_outages = len([d for d in outage_dates if d in late_dates])
        if late_outages > early_outages:
            trend = "degrading"
        elif late_outages < early_outages:
            trend = "improving"
        else:
            trend = "stable"

        scores[eid] = {
            "score": score,
            "outage_days": outage_days,
            "total_days": total_days,
            "trend": trend,
            "last_outage": max(outage_dates),
        }

    return scores
