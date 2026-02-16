"""Tests for GET /api/capabilities/feedback/health endpoint."""

from unittest.mock import AsyncMock


class TestFeedbackHealth:
    """GET /api/capabilities/feedback/health"""

    def test_feedback_health_empty(self, api_hub, api_client):
        """Returns zeros when no feedback data exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_total"] == 0
        assert data["capabilities_with_ml_feedback"] == 0
        assert data["capabilities_with_shadow_feedback"] == 0
        assert data["capabilities_drift_flagged"] == 0
        assert data["activity_labels"] == 0
        assert data["activity_classifier_ready"] is False
        assert data["automation_feedback_count"] == 0

    def test_feedback_health_with_ml_feedback(self, api_hub, api_client):
        """Counts capabilities with ml_accuracy."""

        async def mock_get_cache(key):
            if key == "capabilities":
                return {
                    "data": {
                        "lighting": {"ml_accuracy": 0.85},
                        "climate": {"ml_accuracy": 0.72},
                        "motion": {},
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_total"] == 3
        assert data["capabilities_with_ml_feedback"] == 2

    def test_feedback_health_with_shadow_feedback(self, api_hub, api_client):
        """Counts capabilities with shadow_accuracy."""

        async def mock_get_cache(key):
            if key == "capabilities":
                return {
                    "data": {
                        "lighting": {"shadow_accuracy": 0.9},
                        "climate": {},
                        "motion": {"shadow_accuracy": 0.6},
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_total"] == 3
        assert data["capabilities_with_shadow_feedback"] == 2

    def test_feedback_health_with_drift_flagged(self, api_hub, api_client):
        """Counts drift-flagged capabilities."""

        async def mock_get_cache(key):
            if key == "capabilities":
                return {
                    "data": {
                        "lighting": {"drift_flagged": True},
                        "climate": {"drift_flagged": False},
                        "motion": {"drift_flagged": True},
                        "security": {},
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_total"] == 4
        assert data["capabilities_drift_flagged"] == 2

    def test_feedback_health_with_activity_labels(self, api_hub, api_client):
        """Includes label count and classifier status."""

        async def mock_get_cache(key):
            if key == "activity_labels":
                return {
                    "data": {
                        "label_stats": {
                            "total_labels": 42,
                            "classifier_ready": True,
                        }
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["activity_labels"] == 42
        assert data["activity_classifier_ready"] is True

    def test_feedback_health_with_automation_feedback(self, api_hub, api_client):
        """Includes suggestion count from automation feedback."""

        async def mock_get_cache(key):
            if key == "automation_feedback":
                return {
                    "data": {
                        "per_capability": {
                            "lighting": {"suggested": 5},
                            "climate": {"suggested": 3},
                        }
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["automation_feedback_count"] == 8

    def test_feedback_health_full(self, api_hub, api_client):
        """All channels populated returns complete picture."""

        async def mock_get_cache(key):
            if key == "capabilities":
                return {
                    "data": {
                        "lighting": {
                            "ml_accuracy": 0.85,
                            "shadow_accuracy": 0.9,
                            "drift_flagged": False,
                        },
                        "climate": {
                            "ml_accuracy": 0.72,
                            "drift_flagged": True,
                        },
                        "motion": {
                            "shadow_accuracy": 0.6,
                            "drift_flagged": True,
                        },
                        "security": {},
                    }
                }
            if key == "activity_labels":
                return {
                    "data": {
                        "label_stats": {
                            "total_labels": 150,
                            "classifier_ready": True,
                        }
                    }
                }
            if key == "automation_feedback":
                return {
                    "data": {
                        "per_capability": {
                            "lighting": {"suggested": 10},
                            "climate": {"suggested": 7},
                            "motion": {"suggested": 3},
                        }
                    }
                }
            return None

        api_hub.get_cache = AsyncMock(side_effect=mock_get_cache)

        resp = api_client.get("/api/capabilities/feedback/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_total"] == 4
        assert data["capabilities_with_ml_feedback"] == 2
        assert data["capabilities_with_shadow_feedback"] == 2
        assert data["capabilities_drift_flagged"] == 2
        assert data["activity_labels"] == 150
        assert data["activity_classifier_ready"] is True
        assert data["automation_feedback_count"] == 20
