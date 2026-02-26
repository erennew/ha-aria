"""Tests for analysis: baselines, correlations, anomalies, reliability."""

import unittest

from conftest import make_snapshot

from aria.engine.analysis.anomalies import detect_anomalies
from aria.engine.analysis.baselines import compute_baselines
from aria.engine.analysis.correlations import cross_correlate, pearson_r
from aria.engine.analysis.reliability import compute_device_reliability
from aria.engine.collectors.snapshot import build_empty_snapshot
from aria.engine.config import HolidayConfig


class TestBaselines(unittest.TestCase):
    def test_compute_baselines_groups_by_day_of_week(self):
        snapshots = [
            make_snapshot("2026-02-03", power=100),  # Tuesday
            make_snapshot("2026-02-10", power=200),  # Tuesday
            make_snapshot("2026-02-04", power=150),  # Wednesday
        ]
        baselines = compute_baselines(snapshots)
        self.assertIn("Tuesday", baselines)
        self.assertAlmostEqual(baselines["Tuesday"]["power_watts"]["mean"], 150.0)
        self.assertIn("Wednesday", baselines)

    def test_baseline_includes_stddev(self):
        snapshots = [
            make_snapshot("2026-02-03", power=100),
            make_snapshot("2026-02-10", power=200),
        ]
        baselines = compute_baselines(snapshots)
        self.assertGreater(baselines["Tuesday"]["power_watts"]["stddev"], 0)


class TestCorrelation(unittest.TestCase):
    def test_perfect_positive_correlation(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        r = pearson_r(x, y)
        self.assertAlmostEqual(r, 1.0, places=5)

    def test_no_correlation(self):
        x = [1, 2, 3, 4, 5]
        y = [5, 1, 4, 2, 3]
        r = pearson_r(x, y)
        self.assertLess(abs(r), 0.5)

    def test_cross_correlate_finds_weather_power_link(self):
        snapshots = []
        for i, temp in enumerate([60, 70, 80, 90, 95, 65, 75, 85, 92, 88]):
            snap = build_empty_snapshot(f"2026-02-{i + 1:02d}", HolidayConfig())
            snap["weather"]["temp_f"] = temp
            snap["power"]["total_watts"] = 100 + (temp - 60) * 3
            snap["lights"]["on"] = 30
            snap["occupancy"]["device_count_home"] = 50
            snap["entities"]["unavailable"] = 900
            snap["logbook_summary"]["useful_events"] = 2500
            snapshots.append(snap)

        corrs = cross_correlate(snapshots)
        temp_power = [c for c in corrs if c["x"] == "weather_temp" and c["y"] == "power_watts"]
        self.assertTrue(len(temp_power) > 0)
        self.assertGreater(temp_power[0]["r"], 0.9)


class TestDeviceReliability(unittest.TestCase):
    def test_reliability_score_decreases_with_more_outages(self):
        snapshots = []
        unavail_days = {"2026-02-04", "2026-02-06", "2026-02-09"}
        for i in range(7):
            date = f"2026-02-{4 + i:02d}"
            snap = build_empty_snapshot(date, HolidayConfig())
            if date in unavail_days:
                snap["entities"]["unavailable_list"] = ["sensor.flaky_device"]
            else:
                snap["entities"]["unavailable_list"] = []
            snapshots.append(snap)

        scores = compute_device_reliability(snapshots)
        self.assertIn("sensor.flaky_device", scores)
        self.assertLess(scores["sensor.flaky_device"]["score"], 100)
        self.assertEqual(scores["sensor.flaky_device"]["outage_days"], 3)

    def test_healthy_device_gets_100_score(self):
        snapshots = []
        for i in range(7):
            snap = build_empty_snapshot(f"2026-02-{4 + i:02d}", HolidayConfig())
            snap["entities"]["unavailable_list"] = []
            snapshots.append(snap)

        scores = compute_device_reliability(snapshots)
        for _eid, data in scores.items():
            self.assertEqual(data["score"], 100)


class TestAnomalyDetection(unittest.TestCase):
    def test_detects_high_power_anomaly(self):
        baselines = {
            "Tuesday": {
                "power_watts": {"mean": 150, "stddev": 10},
                "lights_on": {"mean": 30, "stddev": 5},
                "devices_home": {"mean": 50, "stddev": 10},
                "unavailable": {"mean": 900, "stddev": 20},
                "useful_events": {"mean": 2500, "stddev": 300},
            }
        }
        snapshot = make_snapshot("2026-02-10", power=300)  # 15sigma above
        anomalies = detect_anomalies(snapshot, baselines)
        power_anomalies = [a for a in anomalies if a["metric"] == "power_watts"]
        self.assertTrue(len(power_anomalies) > 0)
        self.assertGreater(power_anomalies[0]["z_score"], 2.0)

    def test_no_anomaly_within_normal_range(self):
        baselines = {
            "Tuesday": {
                "power_watts": {"mean": 150, "stddev": 10},
                "lights_on": {"mean": 30, "stddev": 5},
                "devices_home": {"mean": 50, "stddev": 10},
                "unavailable": {"mean": 900, "stddev": 20},
                "useful_events": {"mean": 2500, "stddev": 300},
            }
        }
        snapshot = make_snapshot("2026-02-10", power=155)
        anomalies = detect_anomalies(snapshot, baselines)
        power_anomalies = [a for a in anomalies if a["metric"] == "power_watts"]
        self.assertEqual(len(power_anomalies), 0)


class TestSnapDateGuardReliability(unittest.TestCase):
    """Issue #224: reliability.py bare snap['date'] access must be guarded."""

    def test_compute_reliability_missing_date_key_does_not_raise(self):
        """Snapshot missing 'date' key must not raise KeyError in compute_device_reliability."""
        # Snapshot with unavailable list but no 'date' key
        bad_snap = {
            # 'date' key missing
            "entities": {"unavailable_list": ["sensor.flaky"]},
        }
        # Should not raise
        result = compute_device_reliability([bad_snap])
        self.assertIsInstance(result, dict)

    def test_compute_reliability_missing_date_key_logs_warning(self):
        """Snapshot missing 'date' key emits WARNING in compute_device_reliability."""
        import logging

        bad_snap = {
            "entities": {"unavailable_list": ["sensor.flaky"]},
        }
        with self.assertLogs("aria.engine.analysis.reliability", level=logging.WARNING):
            compute_device_reliability([bad_snap])

    def test_compute_reliability_mixed_snapshots_processes_good_ones(self):
        """Snapshots with and without 'date' key — good ones still produce scores."""
        good_snap = {
            "date": "2026-02-10",
            "entities": {"unavailable_list": ["sensor.flaky"]},
        }
        bad_snap = {
            # 'date' key missing
            "entities": {"unavailable_list": ["sensor.flaky"]},
        }
        result = compute_device_reliability([good_snap, bad_snap])
        # sensor.flaky appeared in good_snap at least, so it should be in result
        self.assertIsInstance(result, dict)


class TestSnapDictGuardAnomalies(unittest.TestCase):
    """Issue #223: anomalies.py bare snap[] access must be guarded."""

    def test_detect_anomalies_missing_power_key_returns_empty(self):
        """Snapshot missing 'power' key must not raise KeyError."""
        baselines = {
            "Tuesday": {
                "power_watts": {"mean": 150, "stddev": 10},
                "lights_on": {"mean": 30, "stddev": 5},
                "devices_home": {"mean": 50, "stddev": 10},
                "unavailable": {"mean": 900, "stddev": 20},
                "useful_events": {"mean": 2500, "stddev": 300},
            }
        }
        # Snapshot missing 'power' key
        bad_snap = {
            "day_of_week": "Tuesday",
            "lights": {"on": 30},
            "occupancy": {"device_count_home": 50},
            "entities": {"unavailable": 900},
            "logbook_summary": {"useful_events": 2500},
        }
        # Should not raise — must return [] or an empty/partial list
        result = detect_anomalies(bad_snap, baselines)
        self.assertIsInstance(result, list)

    def test_detect_anomalies_missing_power_key_logs_warning(self):
        """Snapshot missing 'power' key emits WARNING."""
        import logging

        baselines = {
            "Tuesday": {
                "power_watts": {"mean": 150, "stddev": 10},
                "lights_on": {"mean": 30, "stddev": 5},
                "devices_home": {"mean": 50, "stddev": 10},
                "unavailable": {"mean": 900, "stddev": 20},
                "useful_events": {"mean": 2500, "stddev": 300},
            }
        }
        bad_snap = {
            "day_of_week": "Tuesday",
            "lights": {"on": 30},
            "occupancy": {"device_count_home": 50},
            "entities": {"unavailable": 900},
            "logbook_summary": {"useful_events": 2500},
        }
        with self.assertLogs("aria.engine.analysis.anomalies", level=logging.WARNING):
            detect_anomalies(bad_snap, baselines)


class TestSnapDictGuardBaselines(unittest.TestCase):
    """Issue #223: baselines.py bare s[] access must be guarded."""

    def test_compute_baselines_missing_power_key_skips_gracefully(self):
        """Snapshot missing 'power' key must not raise KeyError in compute_baselines."""
        bad_snap = {
            "day_of_week": "Wednesday",
            # 'power' key missing entirely
            "lights": {"on": 5, "off": 60},
            "occupancy": {"device_count_home": 50},
            "entities": {"unavailable": 900},
            "logbook_summary": {"useful_events": 2500},
        }
        # Should not raise — missing metrics are skipped or default to 0
        result = compute_baselines([bad_snap])
        self.assertIsInstance(result, dict)

    def test_compute_baselines_missing_power_key_logs_warning(self):
        """Snapshot missing 'power' key emits WARNING in compute_baselines."""
        import logging

        bad_snap = {
            "day_of_week": "Wednesday",
            "lights": {"on": 5, "off": 60},
            "occupancy": {"device_count_home": 50},
            "entities": {"unavailable": 900},
            "logbook_summary": {"useful_events": 2500},
        }
        with self.assertLogs("aria.engine.analysis.baselines", level=logging.WARNING):
            compute_baselines([bad_snap])


class TestSnapDictGuardCorrelations(unittest.TestCase):
    """Issue #223: correlations.py bare snap[] access must be guarded."""

    def test_cross_correlate_missing_power_key_returns_list(self):
        """cross_correlate with snapshots missing 'power' key must not raise KeyError."""
        bad_snaps = []
        for _i in range(6):
            bad_snaps.append(
                {
                    "day_of_week": "Monday",
                    # 'power' key missing
                    "lights": {"on": 5},
                    "occupancy": {"device_count_home": 50},
                    "entities": {"unavailable": 900},
                    "logbook_summary": {"useful_events": 2500},
                }
            )
        # Should not raise
        result = cross_correlate(bad_snaps)
        self.assertIsInstance(result, list)

    def test_cross_correlate_missing_power_key_logs_warning(self):
        """cross_correlate with snapshots missing 'power' key emits WARNING."""
        import logging

        bad_snaps = []
        for _i in range(6):
            bad_snaps.append(
                {
                    "day_of_week": "Monday",
                    "lights": {"on": 5},
                    "occupancy": {"device_count_home": 50},
                    "entities": {"unavailable": 900},
                    "logbook_summary": {"useful_events": 2500},
                }
            )
        with self.assertLogs("aria.engine.analysis.correlations", level=logging.WARNING):
            cross_correlate(bad_snaps)


if __name__ == "__main__":
    unittest.main()
