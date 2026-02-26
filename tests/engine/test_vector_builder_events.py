"""Tests for event-derived features in vector_builder."""

import copy

from aria.engine.features.vector_builder import build_feature_vector, get_feature_names
from aria.shared.constants import DEFAULT_FEATURE_CONFIG


def _make_minimal_snapshot():
    """Minimal snapshot with all required sections."""
    return {
        "time_features": {
            "hour_sin": 0.5,
            "hour_cos": 0.87,
            "dow_sin": 0.0,
            "dow_cos": 1.0,
            "month_sin": 0.5,
            "month_cos": 0.87,
            "day_of_year_sin": 0.1,
            "day_of_year_cos": 0.99,
            "is_weekend": False,
            "is_holiday": False,
            "is_night": False,
            "is_work_hours": True,
            "minutes_since_sunrise": 120,
            "minutes_until_sunset": 300,
            "daylight_remaining_pct": 0.7,
        },
        "weather": {"temp_f": 72, "humidity_pct": 50, "wind_mph": 5},
        "occupancy": {"people_home": ["alice"], "device_count_home": 5},
        "lights": {"on": 3, "total_brightness": 200},
        "motion": {"active_count": 1, "sensors": {}},
        "media": {"total_active": 1},
        "power": {"total_watts": 150},
        "ev": {"TARS": {"battery_pct": 80, "is_charging": False}},
        "presence": {
            "overall_probability": 0.9,
            "occupied_room_count": 2,
            "identified_person_count": 1,
            "camera_signal_count": 0,
        },
    }


class TestEventFeaturesInConfig:
    def test_default_config_has_event_features(self):
        assert "event_features" in DEFAULT_FEATURE_CONFIG
        ef = DEFAULT_FEATURE_CONFIG["event_features"]
        assert ef["event_count"] is True
        assert ef["light_transitions"] is True
        assert ef["motion_events"] is True
        assert ef["unique_entities_active"] is True
        assert ef["domain_entropy"] is True

    def test_feature_names_includes_event_features(self):
        names = get_feature_names()
        assert "event_count" in names
        assert "light_transitions" in names
        assert "motion_events" in names
        assert "unique_entities_active" in names
        assert "domain_entropy" in names


class TestEventFeaturesBackwardCompat:
    def test_without_segment_data_unchanged(self):
        """Existing callers passing no segment_data get identical output."""
        snapshot = _make_minimal_snapshot()
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        result_without = build_feature_vector(snapshot, config, None, None)
        result_with_none = build_feature_vector(snapshot, config, None, None, segment_data=None)
        assert result_without == result_with_none

    def test_event_features_zero_without_segment(self):
        """Without segment_data, event features default to 0."""
        snapshot = _make_minimal_snapshot()
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        result = build_feature_vector(snapshot, config, None, None)
        assert result["event_count"] == 0
        assert result["light_transitions"] == 0
        assert result["motion_events"] == 0
        assert result["unique_entities_active"] == 0
        assert result["domain_entropy"] == 0


class TestEventFeaturesWithSegment:
    def test_segment_data_populates_features(self):
        snapshot = _make_minimal_snapshot()
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        segment = {
            "event_count": 42,
            "light_transitions": 5,
            "motion_events": 8,
            "unique_entities_active": 12,
            "domain_entropy": 1.58,
        }
        result = build_feature_vector(snapshot, config, None, None, segment_data=segment)
        assert result["event_count"] == 42
        assert result["light_transitions"] == 5
        assert result["motion_events"] == 8
        assert result["unique_entities_active"] == 12
        assert result["domain_entropy"] == 1.58

    def test_disabled_event_features_excluded(self):
        snapshot = _make_minimal_snapshot()
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        config["event_features"] = {
            "event_count": False,
            "light_transitions": False,
            "motion_events": False,
            "unique_entities_active": False,
            "domain_entropy": False,
        }
        segment = {"event_count": 42, "light_transitions": 5}
        result = build_feature_vector(snapshot, config, None, None, segment_data=segment)
        assert "event_count" not in result
        assert "light_transitions" not in result

    def test_partial_segment_data(self):
        """Segment data missing some keys should default missing to 0."""
        snapshot = _make_minimal_snapshot()
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        segment = {"event_count": 10}  # Only one field
        result = build_feature_vector(snapshot, config, None, None, segment_data=segment)
        assert result["event_count"] == 10
        assert result["light_transitions"] == 0  # Missing from segment → 0

    def test_feature_names_excludes_disabled(self):
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        config["event_features"] = {
            "event_count": False,
            "light_transitions": True,
            "motion_events": False,
            "unique_entities_active": True,
            "domain_entropy": False,
        }
        names = get_feature_names(config)
        assert "event_count" not in names
        assert "light_transitions" in names
        assert "motion_events" not in names
        assert "unique_entities_active" in names
        assert "domain_entropy" not in names


# =============================================================================
# #212 — build_training_data must pass segment_data to build_feature_vector
# =============================================================================


def test_build_training_data_passes_segment_data():
    """#212: build_training_data(segment_data_list=...) must produce non-zero event features."""
    from aria.engine.features.vector_builder import build_training_data
    from aria.shared.constants import DEFAULT_FEATURE_CONFIG

    snapshot = _make_minimal_snapshot()
    segment_data = {
        "event_count": 42,
        "light_transitions": 7,
        "motion_events": 3,
        "unique_entities_active": 10,
        "domain_entropy": 1.5,
    }

    # Without segment_data: all event features are 0
    _, X_no_seg, _ = build_training_data([snapshot], config=DEFAULT_FEATURE_CONFIG)
    feature_names, X_with_seg, _ = build_training_data(
        [snapshot],
        config=DEFAULT_FEATURE_CONFIG,
        segment_data_list=[segment_data],
    )

    event_feature_names = [
        "event_count",
        "light_transitions",
        "motion_events",
        "unique_entities_active",
        "domain_entropy",
    ]

    for feat in event_feature_names:
        if feat in feature_names:
            idx = feature_names.index(feat)
            assert X_no_seg[0][idx] == 0, f"{feat} should be 0 without segment_data"
            assert X_with_seg[0][idx] != 0, f"{feat} should be non-zero when segment_data is provided"
