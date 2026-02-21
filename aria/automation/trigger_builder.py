"""Trigger builder — domain-aware HA trigger type selection.

Maps entity domains to appropriate HA trigger types and constructs
valid trigger dicts for automation YAML generation.
"""

from aria.automation.models import DetectionResult

# States that must be quoted as strings in YAML (HA interprets unquoted on/off as booleans)
YAML_QUOTED_STATES = {"on", "off", "yes", "no", "true", "false", "home", "not_home"}

# Domain → trigger type mapping
DOMAIN_TRIGGER_MAP = {
    "binary_sensor": "state",
    "sensor": "numeric_state",
    "person": "state",
    "device_tracker": "state",
    "switch": "state",
    "input_boolean": "state",
    "light": "state",
    "media_player": "state",
    "cover": "state",
    "lock": "state",
    "fan": "state",
    "climate": "state",
    "alarm_control_panel": "state",
}

DEFAULT_DEBOUNCE_SECONDS = 5


def build_trigger(
    detection: DetectionResult,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> dict:
    """Build an HA trigger dict from a DetectionResult.

    Args:
        detection: The detection result containing trigger entity and chain.
        debounce_seconds: Duration for `for` debounce (0 to omit).

    Returns:
        HA-compatible trigger dict.
    """
    entity_id = detection.trigger_entity
    domain = entity_id.split(".")[0]
    trigger_type = DOMAIN_TRIGGER_MAP.get(domain, "state")

    # Get state from the first chain link (the trigger)
    state = "on"
    if detection.entity_chain:
        state = detection.entity_chain[0].state

    # Generate a stable trigger ID
    trigger_id = _make_trigger_id(entity_id)

    if trigger_type == "numeric_state":
        return _build_numeric_trigger(entity_id, state, trigger_id)

    return _build_state_trigger(entity_id, state, trigger_id, debounce_seconds)


def _build_state_trigger(
    entity_id: str,
    state: str,
    trigger_id: str,
    debounce_seconds: int,
) -> dict:
    """Build a state-type trigger."""
    trigger = {
        "trigger": "state",
        "entity_id": entity_id,
        "to": _quote_state(state),
        "id": trigger_id,
    }
    if debounce_seconds > 0:
        trigger["for"] = _format_duration(debounce_seconds)
    return trigger


def _build_numeric_trigger(
    entity_id: str,
    state: str,
    trigger_id: str,
) -> dict:
    """Build a numeric_state trigger with above/below threshold."""
    trigger: dict = {
        "trigger": "numeric_state",
        "entity_id": entity_id,
        "id": trigger_id,
    }
    try:
        value = float(state)
        # Use the observed value as an "above" threshold
        trigger["above"] = value - 1
        trigger["below"] = value + 1
    except (ValueError, TypeError):
        # Fallback: can't parse as number, use state trigger instead
        trigger["trigger"] = "state"
        trigger["to"] = _quote_state(state)
    return trigger


def _quote_state(state: str) -> str:
    """Force-quote YAML-unsafe state values."""
    if state.lower() in YAML_QUOTED_STATES:
        return f'"{state}"'
    return state


def _format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS duration string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _make_trigger_id(entity_id: str) -> str:
    """Generate a trigger ID from entity_id."""
    # e.g. binary_sensor.bedroom_motion → bedroom_motion_trigger
    parts = entity_id.split(".", 1)
    name = parts[1] if len(parts) > 1 else parts[0]
    return f"{name}_trigger"
