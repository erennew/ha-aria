"""HA Automation Sync — Periodic fetch + incremental hash-based normalization.

Fetches existing Home Assistant automations via REST API, hashes each
for change detection, normalizes entity_id formats, and stores in
the ha_automations cache for shadow comparison.
"""

import copy
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class HaAutomationSync:
    """Fetch and cache HA automations with incremental change detection."""

    def __init__(
        self,
        hub: Any,
        ha_url: str,
        ha_token: str,
        session: aiohttp.ClientSession | None = None,
    ):
        self.hub = hub
        self.ha_url = ha_url.rstrip("/")
        self.ha_token = ha_token
        self._session = session
        self._hashes: dict[str, str] = {}  # automation_id → content hash

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync(self) -> dict[str, Any]:
        """Fetch automations from HA, normalize changed ones, update cache.

        Returns:
            Result dict with success, count, and changes keys.
        """
        try:
            raw_automations = await self._fetch_automations()
        except Exception as e:
            logger.error(f"Failed to fetch HA automations: {e}")
            return {"success": False, "error": str(e)}

        if raw_automations is None:
            return {"success": False, "error": "Failed to fetch automations"}

        if not isinstance(raw_automations, list):
            logger.warning(
                "ha_automation_sync: unexpected response type %s from HA API — expected list, got %r; skipping sync",
                type(raw_automations).__name__,
                raw_automations,
            )
            return {"success": False, "error": f"Unexpected response type: {type(raw_automations).__name__}"}

        # Determine which automations changed
        changes = 0
        normalized = {}

        for auto in raw_automations:
            auto_id = auto.get("id", "")
            if not auto_id:
                continue

            content_hash = self._compute_hash(auto)

            if self._hashes.get(auto_id) != content_hash:
                # New or changed — normalize
                norm = self._normalize_automation(auto)
                normalized[auto_id] = norm
                self._hashes[auto_id] = content_hash
                changes += 1
            else:
                # Unchanged — keep existing normalized version from cache
                existing = await self._get_cached_automation(auto_id)
                if existing:
                    normalized[auto_id] = existing
                else:
                    # Cache miss — normalize anyway
                    normalized[auto_id] = self._normalize_automation(auto)

        # Clean up hashes for removed automations
        current_ids = {a.get("id", "") for a in raw_automations}
        removed_ids = set(self._hashes.keys()) - current_ids
        for rid in removed_ids:
            del self._hashes[rid]

        # Store in cache
        automations_list = list(normalized.values())
        await self.hub.set_cache(
            "ha_automations",
            {
                "automations": automations_list,
                "count": len(automations_list),
                "last_sync": datetime.now(tz=UTC).isoformat(),
                "changes_since_last": changes,
            },
            {"source": "ha_automation_sync"},
        )

        logger.info(f"HA automation sync: {len(automations_list)} automations, {changes} changes")

        return {
            "success": True,
            "count": len(automations_list),
            "changes": changes,
        }

    async def force_sync(self) -> dict[str, Any]:
        """Force re-normalization of all automations (clears hashes).

        Returns:
            Result dict with success, count, and changes keys.
        """
        self._hashes.clear()
        return await self.sync()

    async def add_automation(self, automation: dict[str, Any]) -> None:
        """Immediately add/update an automation in the cache.

        Used by the orchestrator when an automation is created in HA
        to prevent re-suggestion before the next sync cycle.

        Args:
            automation: HA automation config dict.
        """
        auto_id = automation.get("id", "")
        normalized = self._normalize_automation(automation)

        # Load existing cache
        cached = await self.hub.get_cache("ha_automations")
        automations = list(cached["data"].get("automations", [])) if cached and "data" in cached else []

        # Replace existing or append
        replaced = False
        for i, existing in enumerate(automations):
            if existing.get("id") == auto_id:
                automations[i] = normalized
                replaced = True
                break

        if not replaced:
            automations.append(normalized)

        # Update hash
        self._hashes[auto_id] = self._compute_hash(automation)

        # Store updated cache
        await self.hub.set_cache(
            "ha_automations",
            {
                "automations": automations,
                "count": len(automations),
                "last_sync": datetime.now(tz=UTC).isoformat(),
                "changes_since_last": 1,
            },
            {"source": "ha_automation_sync"},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_automations(self) -> list[dict[str, Any]] | None:
        """Fetch automation configs from HA REST API.

        Returns:
            List of automation dicts or None on failure.
        """
        if not self._session:
            return None

        url = f"{self.ha_url}/api/config/automation/config"
        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.get(url, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"HA automation fetch failed: HTTP {response.status} - {text}")
                    return None
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"HA automation fetch network error: {e}")
            raise

    async def _get_cached_automation(self, auto_id: str) -> dict[str, Any] | None:
        """Get a single automation from the current cache by ID."""
        cached = await self.hub.get_cache("ha_automations")
        if not cached or "data" not in cached:
            return None

        for auto in cached["data"].get("automations", []):
            if auto.get("id") == auto_id:
                return auto
        return None

    @staticmethod
    def _compute_hash(automation: dict[str, Any]) -> str:
        """Compute a content hash for change detection."""
        # Sort keys for deterministic hashing
        canonical = json.dumps(automation, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _normalize_automation(self, automation: dict[str, Any]) -> dict[str, Any]:
        """Normalize an HA automation config.

        - Lowercases entity_id values
        - Preserves all other fields

        Args:
            automation: Raw HA automation dict.

        Returns:
            Normalized copy.
        """
        normalized = copy.deepcopy(automation)

        # Ensure both singular and plural keys exist for triggers, conditions, actions
        for singular, plural in [("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")]:
            if singular in normalized and plural not in normalized:
                normalized[plural] = normalized[singular]
            elif plural in normalized and singular not in normalized:
                normalized[singular] = normalized[plural]

        # Normalize entity IDs in triggers
        for trigger in normalized.get("trigger", []):
            self._normalize_entity_id_field(trigger)

        # Normalize entity IDs in conditions
        for condition in normalized.get("condition", []):
            self._normalize_entity_id_field(condition)

        # Normalize entity IDs in actions
        for action in normalized.get("action", []):
            self._normalize_entity_id_field(action)
            # Also check target sub-dict
            target = action.get("target", {})
            if target:
                self._normalize_entity_id_field(target)

        # Sync plural keys after normalization
        for singular, plural in [("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")]:
            if singular in normalized:
                normalized[plural] = normalized[singular]

        return normalized

    @staticmethod
    def _normalize_entity_id_field(obj: dict[str, Any]) -> None:
        """Normalize entity_id field in a dict (in-place).

        Handles both string and list[str] entity_id values.
        """
        if "entity_id" not in obj:
            return

        entity_id = obj["entity_id"]
        if isinstance(entity_id, str):
            obj["entity_id"] = entity_id.lower()
        elif isinstance(entity_id, list):
            obj["entity_id"] = [eid.lower() if isinstance(eid, str) else eid for eid in entity_id]
