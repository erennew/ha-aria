"""Shared YAML utilities used across the automation pipeline.

Centralises state-quoting logic so trigger_builder and condition_builder
both use the same function without cross-module private imports.
"""

# States that must be quoted as strings in YAML
# (HA interprets unquoted on/off/yes/no/true/false/home/not_home as booleans or special values)
YAML_QUOTED_STATES = {"on", "off", "yes", "no", "true", "false", "home", "not_home"}


def quote_state(state: str) -> str:
    """Force-quote YAML-unsafe state values.

    Args:
        state: A HA entity state string.

    Returns:
        The state value, double-quoted if it would be misinterpreted by YAML.
    """
    if state.lower() in YAML_QUOTED_STATES:
        return f'"{state}"'
    return state
