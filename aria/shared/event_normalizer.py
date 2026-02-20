"""Event normalizer — filters, normalizes, and segments EventStore events.

Pipeline orchestrator that applies state filtering, user exclusions,
state normalization, and context tagging. Advanced stages (day
classification, co-occurrence, environmental correlation) are delegated
to separate modules.
"""

import fnmatch
import logging
from typing import Any

logger = logging.getLogger(__name__)

# States that map to semantic "positive" (entity active/triggered)
POSITIVE_STATES = {"on", "True", "true", "detected", "open", "unlocked", "home", "playing", "paused"}
# States that map to semantic "negative" (entity inactive/clear)
NEGATIVE_STATES = {"off", "False", "false", "clear", "closed", "locked", "not_home", "idle", "standby"}


class EventNormalizer:
    """Filters and normalizes raw EventStore events for detection engines."""

    def __init__(self, config: dict[str, Any]):
        self.ignored_states = set(config.get("filter.ignored_states", ["unavailable", "unknown"]))
        self.exclude_entities = set(config.get("filter.exclude_entities", []))
        self.exclude_areas = set(config.get("filter.exclude_areas", []))
        self.exclude_domains = set(config.get("filter.exclude_domains", []))
        self.include_domains = set(config.get("filter.include_domains", []))
        self.exclude_patterns = list(config.get("filter.exclude_entity_patterns", []))
        self.min_availability_pct = config.get("filter.min_availability_pct", 80)

    def filter_states(self, events: list[dict]) -> list[dict]:
        """Remove events where old_state or new_state is in ignored set."""
        return [
            e
            for e in events
            if e.get("old_state") not in self.ignored_states and e.get("new_state") not in self.ignored_states
        ]

    def normalize_state(self, domain: str, state: str) -> str:
        """Map hardware-specific states to semantic equivalents."""
        if state in POSITIVE_STATES:
            return "positive"
        if state in NEGATIVE_STATES:
            return "negative"
        return state  # numeric or unknown states pass through

    def filter_user_exclusions(self, events: list[dict]) -> list[dict]:
        """Apply user-configured entity/area/domain/pattern exclusions."""
        result = []
        for e in events:
            entity_id = e.get("entity_id", "")
            domain = e.get("domain", "")
            area_id = e.get("area_id")

            # Explicit entity exclusion
            if entity_id in self.exclude_entities:
                continue

            # Area exclusion
            if area_id and area_id in self.exclude_areas:
                continue

            # Domain exclusion (whitelist takes precedence)
            if self.include_domains:
                if domain not in self.include_domains:
                    continue
            elif domain in self.exclude_domains:
                continue

            # Glob pattern exclusion
            if any(fnmatch.fnmatch(entity_id, pat) for pat in self.exclude_patterns):
                continue

            result.append(e)
        return result
