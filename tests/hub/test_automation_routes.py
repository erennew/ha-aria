"""Tests for automation API routes — shadow sync, status, compare, health, delete.

Covers Task 30 (Batch 11) endpoints registered via _register_automation_routes().
"""

from unittest.mock import AsyncMock, MagicMock, patch

# ============================================================================
# POST /api/shadow/sync
# ============================================================================


class TestShadowSync:
    def test_sync_no_orchestrator(self, api_hub, api_client):
        """Returns 503 when orchestrator module is not loaded."""
        api_hub.get_module = MagicMock(return_value=None)

        response = api_client.post("/api/shadow/sync")
        assert response.status_code == 503
        assert "Orchestrator" in response.json()["detail"]

    def test_sync_success(self, api_hub, api_client):
        """Successful sync delegates to HaAutomationSync and returns result."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.ha_url = "http://test-host:8123"
        mock_orchestrator.ha_token = "test-token"

        def _get_module(mid):
            if mid == "orchestrator":
                return mock_orchestrator
            return None

        api_hub.get_module = MagicMock(side_effect=_get_module)

        sync_result = {"success": True, "count": 5, "changes": 2}

        with patch("aria.shared.ha_automation_sync.HaAutomationSync") as MockSync:
            instance = MockSync.return_value
            instance.sync = AsyncMock(return_value=sync_result)

            response = api_client.post("/api/shadow/sync")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 5

    def test_sync_triggers_regeneration(self, api_hub, api_client):
        """After successful sync, generator.generate_suggestions() is called."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.ha_url = "http://test-host:8123"
        mock_orchestrator.ha_token = "test-token"

        mock_generator = MagicMock()
        mock_generator.generate_suggestions = AsyncMock(return_value=[])

        def _get_module(mid):
            if mid == "orchestrator":
                return mock_orchestrator
            if mid == "automation_generator":
                return mock_generator
            return None

        api_hub.get_module = MagicMock(side_effect=_get_module)

        with patch("aria.shared.ha_automation_sync.HaAutomationSync") as MockSync:
            instance = MockSync.return_value
            instance.sync = AsyncMock(return_value={"success": True})

            api_client.post("/api/shadow/sync")

        mock_generator.generate_suggestions.assert_awaited_once()

    def test_sync_failure_returns_error(self, api_hub, api_client):
        """When sync returns success=False, the error dict is forwarded."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.ha_url = "http://test-host:8123"
        mock_orchestrator.ha_token = "test-token"
        api_hub.get_module = MagicMock(return_value=mock_orchestrator)

        with patch("aria.shared.ha_automation_sync.HaAutomationSync") as MockSync:
            instance = MockSync.return_value
            instance.sync = AsyncMock(return_value={"success": False, "error": "timeout"})

            response = api_client.post("/api/shadow/sync")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


# ============================================================================
# GET /api/shadow/status
# ============================================================================


class TestShadowStatus:
    def test_status_empty(self, api_hub, api_client):
        """Returns zeroed status when no caches exist."""
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.cache.get_pipeline_state = AsyncMock(return_value=None)

        response = api_client.get("/api/shadow/status")
        assert response.status_code == 200

        data = response.json()
        assert data["ha_automations_count"] == 0
        assert data["suggestions_count"] == 0
        assert data["pipeline_stage"] == "shadow"

    def test_status_with_data(self, api_hub, api_client):
        """Returns populated status from caches."""
        ha_cache = {
            "data": {"automations": {"a1": {}, "a2": {}, "a3": {}}},
            "last_updated": "2026-02-20T10:00:00",
        }
        sug_cache = {
            "data": {"suggestions": [{"id": 1}, {"id": 2}], "count": 2},
            "last_updated": "2026-02-20T11:00:00",
        }

        async def _get_cache(cat):
            if cat == "ha_automations":
                return ha_cache
            if cat == "automation_suggestions":
                return sug_cache
            return None

        api_hub.get_cache = AsyncMock(side_effect=_get_cache)
        api_hub.cache.get_pipeline_state = AsyncMock(return_value={"current_stage": "suggest"})

        response = api_client.get("/api/shadow/status")
        assert response.status_code == 200

        data = response.json()
        assert data["ha_automations_count"] == 3
        assert data["suggestions_count"] == 2
        assert data["pipeline_stage"] == "suggest"


# ============================================================================
# GET /api/shadow/compare
# ============================================================================


class TestShadowCompare:
    def test_compare_empty(self, api_hub, api_client):
        """Returns empty comparisons when no suggestions exist."""
        api_hub.get_cache = AsyncMock(return_value=None)

        response = api_client.get("/api/shadow/compare")
        assert response.status_code == 200

        data = response.json()
        assert data["comparisons"] == []
        assert data["total_suggestions"] == 0

    def test_compare_with_suggestions(self, api_hub, api_client):
        """Returns comparison details per suggestion."""
        suggestions = [
            {
                "suggestion_id": "abc123",
                "shadow_status": "new",
                "shadow_reason": "No matching automation",
                "combined_score": 0.85,
                "status": "pending",
                "metadata": {"trigger_entity": "binary_sensor.motion"},
            },
            {
                "suggestion_id": "def456",
                "shadow_status": "conflict",
                "shadow_reason": "Opposite action",
                "combined_score": 0.72,
                "status": "pending",
                "metadata": {"trigger_entity": "binary_sensor.door"},
            },
        ]

        async def _get_cache(cat):
            if cat == "automation_suggestions":
                return {"data": {"suggestions": suggestions}}
            if cat == "ha_automations":
                return {"data": {"automations": {"a1": {}}}}
            return None

        api_hub.get_cache = AsyncMock(side_effect=_get_cache)

        response = api_client.get("/api/shadow/compare")
        assert response.status_code == 200

        data = response.json()
        assert data["total_suggestions"] == 2
        assert data["total_ha_automations"] == 1
        assert data["status_counts"]["new"] == 1
        assert data["status_counts"]["conflict"] == 1
        assert data["comparisons"][0]["suggestion_id"] == "abc123"


# ============================================================================
# GET /api/automations/health
# ============================================================================


class TestAutomationsHealth:
    def test_health_from_cache(self, api_hub, api_client):
        """Returns cached health data when automation_system_health exists."""
        health_data = {
            "suggestions_total": 5,
            "suggestions_pending": 3,
            "generator_loaded": True,
        }
        api_hub.get_cache = AsyncMock(return_value={"data": health_data})

        response = api_client.get("/api/automations/health")
        assert response.status_code == 200

        data = response.json()
        assert data["suggestions_total"] == 5

    def test_health_live_fallback(self, api_hub, api_client):
        """Builds live health summary when cache is empty."""
        suggestions = [
            {"status": "pending"},
            {"status": "pending"},
            {"status": "approved"},
        ]

        call_count = 0

        async def _get_cache(cat):
            nonlocal call_count
            call_count += 1
            if cat == "automation_system_health":
                return None  # No cached health
            if cat == "automation_suggestions":
                return {"data": {"suggestions": suggestions}}
            if cat == "ha_automations":
                return {"data": {"automations": {"a1": {}}}}
            if cat == "automation_feedback":
                return {"data": {"suggestions": {"s1": {}, "s2": {}}}}
            return None

        api_hub.get_cache = AsyncMock(side_effect=_get_cache)
        api_hub.cache.get_pipeline_state = AsyncMock(return_value={"current_stage": "shadow"})
        api_hub.get_module = MagicMock(return_value=None)

        response = api_client.get("/api/automations/health")
        assert response.status_code == 200

        data = response.json()
        assert data["suggestions_total"] == 3
        assert data["suggestions_pending"] == 2
        assert data["suggestions_approved"] == 1
        assert data["ha_automations_count"] == 1
        assert data["feedback_count"] == 2


# ============================================================================
# DELETE /api/automations/{suggestion_id}
# ============================================================================


class TestDeleteAutomation:
    def test_delete_not_found_no_cache(self, api_hub, api_client):
        """Returns 404 when no suggestions cache exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        response = api_client.delete("/api/automations/abc123")
        assert response.status_code == 404

    def test_delete_not_found_missing_id(self, api_hub, api_client):
        """Returns 404 when suggestion_id does not exist."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "suggestions": [{"suggestion_id": "other"}],
                    "count": 1,
                }
            }
        )

        response = api_client.delete("/api/automations/abc123")
        assert response.status_code == 404
        assert "abc123" in response.json()["detail"]

    def test_delete_success(self, api_hub, api_client):
        """Successfully deletes a suggestion and updates cache."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "suggestions": [
                        {"suggestion_id": "abc123"},
                        {"suggestion_id": "def456"},
                    ],
                    "count": 2,
                }
            }
        )

        response = api_client.delete("/api/automations/abc123")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "deleted"
        assert data["suggestion_id"] == "abc123"
        assert data["remaining"] == 1

        # Verify set_cache was called with filtered list
        api_hub.set_cache.assert_awaited_once()
        call_args = api_hub.set_cache.call_args
        assert call_args[0][0] == "automation_suggestions"
        saved_data = call_args[0][1]
        assert len(saved_data["suggestions"]) == 1
        assert saved_data["suggestions"][0]["suggestion_id"] == "def456"
