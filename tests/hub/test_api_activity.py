"""Tests for /api/activity/* endpoints."""

from unittest.mock import AsyncMock, MagicMock


class TestGetCurrentActivity:
    """GET /api/activity/current"""

    def test_get_current_activity_empty(self, api_hub, api_client):
        """Returns default when no cache exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        resp = api_client.get("/api/activity/current")

        assert resp.status_code == 200
        data = resp.json()
        assert data["predicted"] == "unknown"
        assert data["confidence"] == 0
        assert data["method"] == "none"

    def test_get_current_activity_with_data(self, api_hub, api_client):
        """Returns cached current activity."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "current_activity": {
                        "predicted": "sleeping",
                        "confidence": 0.85,
                        "method": "classifier",
                        "sensor_context": {"bedroom_motion": False},
                    }
                }
            }
        )

        resp = api_client.get("/api/activity/current")

        assert resp.status_code == 200
        data = resp.json()
        assert data["predicted"] == "sleeping"
        assert data["confidence"] == 0.85
        assert data["method"] == "classifier"


class TestPostActivityLabel:
    """POST /api/activity/label"""

    def test_post_activity_label_confirmed(self, api_hub, api_client):
        """Confirmed label when predicted == actual."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "current_activity": {
                        "predicted": "cooking",
                        "confidence": 0.7,
                        "sensor_context": {"kitchen_motion": True},
                    }
                }
            }
        )
        mock_labeler = MagicMock()
        mock_labeler.record_label = AsyncMock(return_value={"total_labels": 1})
        api_hub.modules["activity_labeler"] = mock_labeler

        resp = api_client.post(
            "/api/activity/label",
            json={
                "actual_activity": "cooking",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["predicted"] == "cooking"
        assert data["actual"] == "cooking"
        assert data["source"] == "confirmed"
        assert data["stats"] == {"total_labels": 1}

    def test_post_activity_label_corrected(self, api_hub, api_client):
        """Corrected label when predicted != actual."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "current_activity": {
                        "predicted": "sleeping",
                        "confidence": 0.6,
                        "sensor_context": {"bedroom_motion": True},
                    }
                }
            }
        )
        mock_labeler = MagicMock()
        mock_labeler.record_label = AsyncMock(return_value={"total_labels": 2})
        api_hub.modules["activity_labeler"] = mock_labeler

        resp = api_client.post(
            "/api/activity/label",
            json={
                "actual_activity": "reading",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["predicted"] == "sleeping"
        assert data["actual"] == "reading"
        assert data["source"] == "corrected"
        assert data["stats"] == {"total_labels": 2}

    def test_post_activity_label_missing_field(self, api_hub, api_client):
        """Returns 400 when actual_activity is missing."""
        resp = api_client.post("/api/activity/label", json={})

        assert resp.status_code == 400
        assert "actual_activity required" in resp.json()["error"]

    def test_post_activity_label_no_labeler_module(self, api_hub, api_client):
        """Records label even without labeler module loaded."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "current_activity": {
                        "predicted": "away",
                        "confidence": 0.9,
                        "sensor_context": {},
                    }
                }
            }
        )
        # No labeler module registered
        api_hub.modules = {}

        resp = api_client.post(
            "/api/activity/label",
            json={
                "actual_activity": "away",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["source"] == "confirmed"
        assert "stats" not in data


class TestGetActivityLabels:
    """GET /api/activity/labels"""

    def test_get_activity_labels_empty(self, api_hub, api_client):
        """Returns empty list when no cache exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        resp = api_client.get("/api/activity/labels")

        assert resp.status_code == 200
        data = resp.json()
        assert data["labels"] == []
        assert data["label_stats"] == {}

    def test_get_activity_labels_with_data(self, api_hub, api_client):
        """Returns labels and stats from cache."""
        labels = [
            {"predicted": "sleeping", "actual": "sleeping", "source": "confirmed"},
            {"predicted": "cooking", "actual": "eating", "source": "corrected"},
            {"predicted": "away", "actual": "away", "source": "confirmed"},
        ]
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "labels": labels,
                    "label_stats": {"total_labels": 3, "classifier_ready": False},
                }
            }
        )

        resp = api_client.get("/api/activity/labels")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["labels"]) == 3
        assert data["label_stats"]["total_labels"] == 3


class TestGetActivityStats:
    """GET /api/activity/stats"""

    def test_get_activity_stats_empty(self, api_hub, api_client):
        """Returns defaults when no cache exists."""
        api_hub.get_cache = AsyncMock(return_value=None)

        resp = api_client.get("/api/activity/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_labels"] == 0
        assert data["classifier_ready"] is False

    def test_get_activity_stats(self, api_hub, api_client):
        """Returns label stats from cache."""
        api_hub.get_cache = AsyncMock(
            return_value={
                "data": {
                    "label_stats": {
                        "total_labels": 25,
                        "classifier_ready": True,
                        "accuracy": 0.88,
                    }
                }
            }
        )

        resp = api_client.get("/api/activity/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_labels"] == 25
        assert data["classifier_ready"] is True
        assert data["accuracy"] == 0.88
