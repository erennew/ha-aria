"""Tests for /api/automations/feedback endpoints."""

import pytest
from unittest.mock import AsyncMock


class TestPostAutomationFeedback:
    """POST /api/automations/feedback"""

    def test_record_valid_feedback(self, api_hub, api_client):
        """Records feedback and returns suggestion_id."""
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.set_cache = AsyncMock(return_value=1)

        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-001",
            "capability_source": "lighting_control",
            "user_action": "accepted",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["suggestion_id"] == "sug-001"

        # Verify cache was written with correct structure
        api_hub.set_cache.assert_called_once()
        call_args = api_hub.set_cache.call_args
        assert call_args[0][0] == "automation_feedback"
        written_data = call_args[0][1]
        assert "sug-001" in written_data["suggestions"]
        assert written_data["suggestions"]["sug-001"]["user_action"] == "accepted"
        assert written_data["per_capability"]["lighting_control"]["suggested"] == 1
        assert written_data["per_capability"]["lighting_control"]["accepted"] == 1
        assert written_data["per_capability"]["lighting_control"]["acceptance_rate"] == 1.0
        assert call_args[0][2] == {"source": "user_feedback"}

    def test_record_rejected_feedback(self, api_hub, api_client):
        """Records rejected feedback and updates counters."""
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.set_cache = AsyncMock(return_value=1)

        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-002",
            "capability_source": "climate_control",
            "user_action": "rejected",
        })

        assert resp.status_code == 200
        written_data = api_hub.set_cache.call_args[0][1]
        cap = written_data["per_capability"]["climate_control"]
        assert cap["suggested"] == 1
        assert cap["rejected"] == 1
        assert cap["accepted"] == 0
        assert cap["acceptance_rate"] == 0.0

    def test_record_modified_feedback(self, api_hub, api_client):
        """Modified action is valid but does not increment accepted/rejected."""
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.set_cache = AsyncMock(return_value=1)

        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-003",
            "capability_source": "lighting_control",
            "user_action": "modified",
        })

        assert resp.status_code == 200
        written_data = api_hub.set_cache.call_args[0][1]
        cap = written_data["per_capability"]["lighting_control"]
        assert cap["suggested"] == 1
        assert cap["accepted"] == 0
        assert cap["rejected"] == 0

    def test_record_ignored_feedback(self, api_hub, api_client):
        """Ignored action is valid but does not increment accepted/rejected."""
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.set_cache = AsyncMock(return_value=1)

        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-004",
            "capability_source": "lighting_control",
            "user_action": "ignored",
        })

        assert resp.status_code == 200
        written_data = api_hub.set_cache.call_args[0][1]
        cap = written_data["per_capability"]["lighting_control"]
        assert cap["suggested"] == 1
        assert cap["accepted"] == 0
        assert cap["rejected"] == 0

    def test_invalid_user_action_returns_400(self, api_hub, api_client):
        """Invalid user_action returns 400."""
        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-005",
            "capability_source": "lighting_control",
            "user_action": "invalid_action",
        })

        assert resp.status_code == 400
        assert "Invalid user_action" in resp.json()["error"]

    def test_missing_fields_returns_400(self, api_hub, api_client):
        """Missing required fields returns 400."""
        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-006",
        })

        assert resp.status_code == 400
        assert "Missing required fields" in resp.json()["error"]

    def test_appends_to_existing_feedback(self, api_hub, api_client):
        """New feedback appends to existing cache data."""
        existing_data = {
            "data": {
                "suggestions": {
                    "sug-existing": {
                        "capability_source": "lighting_control",
                        "user_action": "accepted",
                        "timestamp": "2026-02-15T00:00:00",
                    }
                },
                "per_capability": {
                    "lighting_control": {
                        "suggested": 1,
                        "accepted": 1,
                        "rejected": 0,
                        "acceptance_rate": 1.0,
                    }
                },
            }
        }
        api_hub.get_cache = AsyncMock(return_value=existing_data)
        api_hub.set_cache = AsyncMock(return_value=2)

        resp = api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-new",
            "capability_source": "lighting_control",
            "user_action": "rejected",
        })

        assert resp.status_code == 200
        written_data = api_hub.set_cache.call_args[0][1]
        # Both suggestions present
        assert "sug-existing" in written_data["suggestions"]
        assert "sug-new" in written_data["suggestions"]
        # Counters updated
        cap = written_data["per_capability"]["lighting_control"]
        assert cap["suggested"] == 2
        assert cap["accepted"] == 1
        assert cap["rejected"] == 1
        assert cap["acceptance_rate"] == 0.5


class TestGetAutomationFeedback:
    """GET /api/automations/feedback"""

    def test_returns_empty_when_no_data(self, api_hub, api_client):
        """Returns empty structure when no feedback exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        resp = api_client.get("/api/automations/feedback")

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"suggestions": {}, "per_capability": {}}

    def test_returns_existing_feedback(self, api_hub, api_client):
        """Returns stored feedback data."""
        feedback_data = {
            "data": {
                "suggestions": {
                    "sug-001": {
                        "capability_source": "lighting_control",
                        "user_action": "accepted",
                        "timestamp": "2026-02-15T12:00:00",
                    }
                },
                "per_capability": {
                    "lighting_control": {
                        "suggested": 1,
                        "accepted": 1,
                        "rejected": 0,
                        "acceptance_rate": 1.0,
                    }
                },
            }
        }
        api_hub.get_cache = AsyncMock(return_value=feedback_data)

        resp = api_client.get("/api/automations/feedback")

        assert resp.status_code == 200
        data = resp.json()
        assert "sug-001" in data["suggestions"]
        assert data["per_capability"]["lighting_control"]["accepted"] == 1

    def test_returns_data_after_post(self, api_hub, api_client):
        """GET returns data that was previously POSTed."""
        # First POST
        api_hub.get_cache = AsyncMock(return_value=None)
        api_hub.set_cache = AsyncMock(return_value=1)

        api_client.post("/api/automations/feedback", json={
            "suggestion_id": "sug-roundtrip",
            "capability_source": "climate_control",
            "user_action": "accepted",
        })

        # Capture what was written
        written_data = api_hub.set_cache.call_args[0][1]

        # Mock GET to return what was written
        api_hub.get_cache = AsyncMock(return_value={"data": written_data})

        resp = api_client.get("/api/automations/feedback")

        assert resp.status_code == 200
        data = resp.json()
        assert "sug-roundtrip" in data["suggestions"]
        assert data["suggestions"]["sug-roundtrip"]["user_action"] == "accepted"
        assert data["per_capability"]["climate_control"]["acceptance_rate"] == 1.0
