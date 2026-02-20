"""Tests for event normalizer pipeline."""

import pytest

from aria.shared.event_normalizer import EventNormalizer


@pytest.fixture
def normalizer():
    config = {
        "filter.ignored_states": ["unavailable", "unknown"],
        "filter.exclude_entities": ["sensor.test_debug"],
        "filter.exclude_areas": ["garage"],
        "filter.exclude_domains": ["automation", "script", "scene"],
        "filter.include_domains": [],
        "filter.exclude_entity_patterns": ["*_battery", "*_signal_strength"],
        "filter.min_availability_pct": 80,
    }
    return EventNormalizer(config)


class TestStateFiltering:
    def test_filter_unavailable_transition(self, normalizer):
        events = [
            {
                "timestamp": "2026-02-20T07:00:00",
                "entity_id": "light.bed",
                "domain": "light",
                "old_state": "on",
                "new_state": "unavailable",
                "area_id": "bedroom",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 0

    def test_keep_normal_transition(self, normalizer):
        events = [
            {
                "timestamp": "2026-02-20T07:00:00",
                "entity_id": "light.bed",
                "domain": "light",
                "old_state": "off",
                "new_state": "on",
                "area_id": "bedroom",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 1

    def test_filter_both_directions(self, normalizer):
        """Both to-unavailable and from-unavailable are filtered."""
        events = [
            {
                "timestamp": "2026-02-20T07:00:00",
                "entity_id": "light.bed",
                "domain": "light",
                "old_state": "unavailable",
                "new_state": "on",
                "area_id": "bedroom",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 0


class TestStateNormalization:
    def test_on_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "on") == "positive"

    def test_off_normalizes_to_negative(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "off") == "negative"

    def test_detected_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "detected") == "positive"

    def test_true_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "True") == "positive"

    def test_non_binary_passes_through(self, normalizer):
        assert normalizer.normalize_state("light", "on") == "positive"

    def test_unknown_state_passes_through(self, normalizer):
        assert normalizer.normalize_state("sensor", "23.5") == "23.5"


class TestUserExclusion:
    def test_exclude_entity(self, normalizer):
        events = [
            {
                "entity_id": "sensor.test_debug",
                "domain": "sensor",
                "area_id": None,
                "timestamp": "t",
                "old_state": "1",
                "new_state": "2",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_area(self, normalizer):
        events = [
            {
                "entity_id": "light.garage",
                "domain": "light",
                "area_id": "garage",
                "timestamp": "t",
                "old_state": "off",
                "new_state": "on",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_domain(self, normalizer):
        events = [
            {
                "entity_id": "automation.test",
                "domain": "automation",
                "area_id": None,
                "timestamp": "t",
                "old_state": "off",
                "new_state": "on",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_glob_pattern(self, normalizer):
        events = [
            {
                "entity_id": "sensor.bedroom_battery",
                "domain": "sensor",
                "area_id": "bedroom",
                "timestamp": "t",
                "old_state": "90",
                "new_state": "89",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_keep_valid_entity(self, normalizer):
        events = [
            {
                "entity_id": "light.bedroom",
                "domain": "light",
                "area_id": "bedroom",
                "timestamp": "t",
                "old_state": "off",
                "new_state": "on",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 1
