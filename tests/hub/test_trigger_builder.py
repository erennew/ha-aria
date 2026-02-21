"""Tests for trigger builder — domain-aware HA trigger type selection."""

from aria.automation.models import ChainLink, DetectionResult
from aria.automation.trigger_builder import build_trigger


def _detection(  # noqa: PLR0913 — test helper with many optional fields
    trigger_entity="binary_sensor.bedroom_motion",
    action_entities=None,
    entity_chain=None,
    area_id="bedroom",
    confidence=0.85,
    day_type="workday",
):
    """Helper to build a DetectionResult for trigger tests."""
    if action_entities is None:
        action_entities = ["light.bedroom"]
    if entity_chain is None:
        entity_chain = [
            ChainLink(entity_id=trigger_entity, state="on", offset_seconds=0),
            ChainLink(entity_id=action_entities[0], state="on", offset_seconds=30),
        ]
    return DetectionResult(
        source="pattern",
        trigger_entity=trigger_entity,
        action_entities=action_entities,
        entity_chain=entity_chain,
        area_id=area_id,
        confidence=confidence,
        recency_weight=0.9,
        observation_count=47,
        first_seen="2026-01-01T06:30:00",
        last_seen="2026-02-19T06:45:00",
        day_type=day_type,
        combined_score=0.8,
    )


class TestTriggerTypeSelection:
    """Test domain → trigger type mapping."""

    def test_binary_sensor_motion_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="binary_sensor.bedroom_motion"))
        assert result["trigger"] == "state"
        assert result["entity_id"] == "binary_sensor.bedroom_motion"
        assert result["to"] == '"on"'

    def test_binary_sensor_door_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="binary_sensor.front_door"))
        assert result["trigger"] == "state"

    def test_sensor_numeric_state_trigger(self):
        det = _detection(trigger_entity="sensor.bedroom_temperature")
        det.entity_chain[0].state = "23.5"
        result = build_trigger(det)
        assert result["trigger"] == "numeric_state"
        assert result["entity_id"] == "sensor.bedroom_temperature"

    def test_person_zone_trigger(self):
        result = build_trigger(_detection(trigger_entity="person.justin"))
        assert result["trigger"] == "state"
        assert result["entity_id"] == "person.justin"

    def test_switch_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="switch.coffee_maker"))
        assert result["trigger"] == "state"
        assert result["entity_id"] == "switch.coffee_maker"

    def test_input_boolean_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="input_boolean.guest_mode"))
        assert result["trigger"] == "state"

    def test_device_tracker_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="device_tracker.phone"))
        assert result["trigger"] == "state"

    def test_light_state_trigger(self):
        result = build_trigger(_detection(trigger_entity="light.kitchen"))
        assert result["trigger"] == "state"


class TestDebounce:
    """Test `for` debounce duration on triggers."""

    def test_default_debounce(self):
        result = build_trigger(_detection())
        assert "for" in result
        # Default 5s debounce
        assert result["for"] == "00:00:05"

    def test_custom_debounce(self):
        result = build_trigger(_detection(), debounce_seconds=10)
        assert result["for"] == "00:00:10"

    def test_zero_debounce_omitted(self):
        result = build_trigger(_detection(), debounce_seconds=0)
        assert "for" not in result


class TestTriggerStateValue:
    """Test state values are correctly extracted and quoted."""

    def test_on_state_quoted(self):
        result = build_trigger(_detection())
        assert result["to"] == '"on"'

    def test_off_state_quoted(self):
        det = _detection()
        det.entity_chain[0].state = "off"
        result = build_trigger(det)
        assert result["to"] == '"off"'

    def test_numeric_state_not_quoted(self):
        det = _detection(trigger_entity="sensor.temperature")
        det.entity_chain[0].state = "23.5"
        result = build_trigger(det)
        # numeric_state triggers use above/below, not to
        assert "above" in result or "below" in result or "to" not in result

    def test_home_state_for_person(self):
        det = _detection(trigger_entity="person.justin")
        det.entity_chain[0].state = "home"
        result = build_trigger(det)
        assert result["to"] == '"home"'


class TestTriggerStructure:
    """Test the trigger dict structure matches HA schema."""

    def test_has_required_keys(self):
        result = build_trigger(_detection())
        assert "trigger" in result
        assert "entity_id" in result

    def test_trigger_id_generated(self):
        result = build_trigger(_detection())
        assert "id" in result
        assert isinstance(result["id"], str)
        assert len(result["id"]) > 0
