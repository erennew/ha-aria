"""Tests for event normalizer pipeline."""

import pytest

from aria.automation.models import DayContext
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

    def test_area_exclusion_with_entity_graph(self):
        """Entity without area_id excluded via entity_graph area resolution."""
        from aria.shared.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.update(
            entities={
                "light.garage_door": {"device_id": "dev_g", "area_id": None},
            },
            devices={
                "dev_g": {"area_id": "garage"},
            },
            areas=[
                {"area_id": "garage", "name": "Garage"},
            ],
        )

        config = {
            "filter.ignored_states": ["unavailable", "unknown"],
            "filter.exclude_entities": [],
            "filter.exclude_areas": ["garage"],
            "filter.exclude_domains": [],
            "filter.include_domains": [],
            "filter.exclude_entity_patterns": [],
            "filter.min_availability_pct": 80,
        }
        normalizer_with_graph = EventNormalizer(config, entity_graph=graph)

        events = [
            {
                "entity_id": "light.garage_door",
                "domain": "light",
                "area_id": None,  # No direct area_id — graph resolves to "garage"
                "timestamp": "t",
                "old_state": "off",
                "new_state": "on",
                "device_id": None,
                "context_parent_id": None,
                "attributes_json": None,
            },
        ]
        result = normalizer_with_graph.filter_user_exclusions(events)
        assert len(result) == 0, "Entity in excluded area (via graph) should be filtered"


class TestDayTypeSegmentation:
    def test_segment_workday_and_weekend(self, normalizer):
        """Events split correctly between workday and weekend pools."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="workday"),  # Monday
            DayContext(date="2026-02-21", day_type="weekend"),  # Saturday
        ]
        events = [
            {"timestamp": "2026-02-16T07:00:00", "entity_id": "light.bed"},
            {"timestamp": "2026-02-16T08:00:00", "entity_id": "light.kitchen"},
            {"timestamp": "2026-02-21T10:00:00", "entity_id": "light.bed"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert len(result["workday"]) == 2
        assert len(result["weekend"]) == 1

    def test_vacation_excluded(self, normalizer):
        """Vacation days are excluded from segmentation."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="vacation", away_all_day=True),
        ]
        events = [
            {"timestamp": "2026-02-16T07:00:00", "entity_id": "light.bed"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert "vacation" not in result
        assert sum(len(v) for v in result.values()) == 0

    def test_holiday_separate_pool(self, normalizer):
        """Holiday events get their own pool (not merged into weekend)."""
        day_contexts = [
            DayContext(date="2026-12-25", day_type="holiday"),
        ]
        events = [
            {"timestamp": "2026-12-25T10:00:00", "entity_id": "light.tree"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert len(result.get("holiday", [])) == 1

    def test_wfh_separate_pool(self, normalizer):
        """WFH events get their own pool."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="wfh"),
        ]
        events = [
            {"timestamp": "2026-02-16T09:00:00", "entity_id": "light.office"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert len(result.get("wfh", [])) == 1

    def test_unknown_day_goes_to_workday(self, normalizer):
        """Events on days not in day_contexts default to workday."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="workday"),
        ]
        events = [
            {"timestamp": "2026-02-17T07:00:00", "entity_id": "light.bed"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert len(result.get("workday", [])) == 1

    def test_empty_events(self, normalizer):
        """Empty event list returns empty pools."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="workday"),
        ]
        result = normalizer.segment_by_day_type([], day_contexts)
        assert sum(len(v) for v in result.values()) == 0

    def test_multiple_day_types(self, normalizer):
        """Multiple day types segmented correctly."""
        day_contexts = [
            DayContext(date="2026-02-16", day_type="workday"),
            DayContext(date="2026-02-17", day_type="wfh"),
            DayContext(date="2026-02-18", day_type="holiday"),
            DayContext(date="2026-02-21", day_type="weekend"),
        ]
        events = [
            {"timestamp": "2026-02-16T07:00:00", "entity_id": "light.a"},
            {"timestamp": "2026-02-17T09:00:00", "entity_id": "light.b"},
            {"timestamp": "2026-02-18T10:00:00", "entity_id": "light.c"},
            {"timestamp": "2026-02-21T11:00:00", "entity_id": "light.d"},
        ]
        result = normalizer.segment_by_day_type(events, day_contexts)
        assert len(result["workday"]) == 1
        assert len(result["wfh"]) == 1
        assert len(result["holiday"]) == 1
        assert len(result["weekend"]) == 1
