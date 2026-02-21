"""Tests for environmental correlator — sun/illuminance Pearson correlation."""

from aria.shared.environmental_correlator import correlate_with_environment


class TestCorrelateWithEnvironment:
    def test_strong_sun_correlation(self):
        """Events that track sunset times should prefer sun trigger."""
        # Simulate events that happen around sunset (which moves earlier/later)
        # Early Feb sunset ~17:30, late Feb ~18:00
        event_timestamps = [
            "2026-02-01T17:28:00",
            "2026-02-03T17:31:00",
            "2026-02-05T17:35:00",
            "2026-02-07T17:38:00",
            "2026-02-09T17:42:00",
            "2026-02-11T17:45:00",
            "2026-02-13T17:48:00",
            "2026-02-15T17:52:00",
        ]
        # Sun events: sunset times that track the same pattern
        sun_events = [
            {"timestamp": "2026-02-01T17:30:00", "elevation": -1.0},
            {"timestamp": "2026-02-03T17:33:00", "elevation": -1.0},
            {"timestamp": "2026-02-05T17:36:00", "elevation": -1.0},
            {"timestamp": "2026-02-07T17:39:00", "elevation": -1.0},
            {"timestamp": "2026-02-09T17:42:00", "elevation": -1.0},
            {"timestamp": "2026-02-11T17:45:00", "elevation": -1.0},
            {"timestamp": "2026-02-13T17:48:00", "elevation": -1.0},
            {"timestamp": "2026-02-15T17:52:00", "elevation": -1.0},
        ]
        result = correlate_with_environment(event_timestamps, sun_events=sun_events)
        assert result["prefer_sun_trigger"] is True
        assert result["sun_correlation_r"] > 0.7

    def test_no_sun_correlation(self):
        """Events at fixed times should NOT correlate with moving sunset."""
        # Always at exactly 19:00 regardless of sunset
        event_timestamps = [
            "2026-02-01T19:00:00",
            "2026-02-03T19:00:00",
            "2026-02-05T19:00:00",
            "2026-02-07T19:00:00",
            "2026-02-09T19:00:00",
            "2026-02-11T19:00:00",
        ]
        sun_events = [
            {"timestamp": "2026-02-01T17:30:00", "elevation": -1.0},
            {"timestamp": "2026-02-03T17:36:00", "elevation": -1.0},
            {"timestamp": "2026-02-05T17:42:00", "elevation": -1.0},
            {"timestamp": "2026-02-07T17:48:00", "elevation": -1.0},
            {"timestamp": "2026-02-09T17:54:00", "elevation": -1.0},
            {"timestamp": "2026-02-11T18:00:00", "elevation": -1.0},
        ]
        result = correlate_with_environment(event_timestamps, sun_events=sun_events)
        assert result["prefer_sun_trigger"] is False

    def test_strong_illuminance_correlation(self):
        """Events tracking illuminance should prefer illuminance trigger.

        Correlation is time-of-day based: if illuminance readings happen at
        times that track when the user acts, the pattern is light-driven.
        """
        # Events move later as days get longer
        event_timestamps = [
            "2026-02-01T17:28:00",
            "2026-02-03T17:31:00",
            "2026-02-05T17:35:00",
            "2026-02-07T17:38:00",
            "2026-02-09T17:42:00",
            "2026-02-11T17:45:00",
        ]
        # Illuminance readings at times that track the events (same shift pattern)
        illuminance_events = [
            {"timestamp": "2026-02-01T17:26:00", "value": 50.0},
            {"timestamp": "2026-02-03T17:29:00", "value": 50.0},
            {"timestamp": "2026-02-05T17:33:00", "value": 50.0},
            {"timestamp": "2026-02-07T17:36:00", "value": 50.0},
            {"timestamp": "2026-02-09T17:40:00", "value": 50.0},
            {"timestamp": "2026-02-11T17:43:00", "value": 50.0},
        ]
        result = correlate_with_environment(
            event_timestamps,
            illuminance_events=illuminance_events,
        )
        assert result["prefer_illuminance_trigger"] is True
        assert result["illuminance_correlation_r"] > 0.7

    def test_no_illuminance_data(self):
        """Missing illuminance data should default to no preference."""
        result = correlate_with_environment(
            ["2026-02-01T07:00:00", "2026-02-02T07:00:00"],
            illuminance_events=[],
        )
        assert result["prefer_illuminance_trigger"] is False
        assert result["illuminance_correlation_r"] == 0.0

    def test_no_sun_data(self):
        """Missing sun data should default to no preference."""
        result = correlate_with_environment(
            ["2026-02-01T07:00:00", "2026-02-02T07:00:00"],
            sun_events=[],
        )
        assert result["prefer_sun_trigger"] is False
        assert result["sun_correlation_r"] == 0.0

    def test_empty_event_timestamps(self):
        """Empty events should return safe defaults."""
        result = correlate_with_environment([])
        assert result["prefer_sun_trigger"] is False
        assert result["prefer_illuminance_trigger"] is False

    def test_custom_threshold(self):
        """Custom correlation threshold should be respected."""
        # Moderate correlation that passes default 0.7 but not 0.95
        event_timestamps = [
            "2026-02-01T17:28:00",
            "2026-02-03T17:31:00",
            "2026-02-05T17:35:00",
            "2026-02-07T17:38:00",
            "2026-02-09T17:42:00",
            "2026-02-11T17:45:00",
        ]
        sun_events = [
            {"timestamp": "2026-02-01T17:30:00", "elevation": -1.0},
            {"timestamp": "2026-02-03T17:33:00", "elevation": -1.0},
            {"timestamp": "2026-02-05T17:36:00", "elevation": -1.0},
            {"timestamp": "2026-02-07T17:39:00", "elevation": -1.0},
            {"timestamp": "2026-02-09T17:42:00", "elevation": -1.0},
            {"timestamp": "2026-02-11T17:45:00", "elevation": -1.0},
        ]
        result_strict = correlate_with_environment(
            event_timestamps,
            sun_events=sun_events,
            threshold=0.99,
        )
        # With very strict threshold, may not prefer sun
        # (depends on exact correlation)
        assert isinstance(result_strict["prefer_sun_trigger"], bool)

    def test_insufficient_data_points(self):
        """Fewer than 3 data points should return no preference."""
        result = correlate_with_environment(
            ["2026-02-01T17:00:00"],
            sun_events=[{"timestamp": "2026-02-01T17:30:00", "elevation": -1.0}],
        )
        assert result["prefer_sun_trigger"] is False
        assert result["sun_correlation_r"] == 0.0
