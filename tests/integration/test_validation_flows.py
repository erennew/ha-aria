"""Cross-layer flow validation — engine to hub, cache persistence, WebSocket."""

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from aria.hub.api import create_api
from aria.hub.core import IntelligenceHub


class TestEngineToHubHandoff:
    """Engine JSON output should be readable by hub Intelligence module."""

    def test_engine_produces_prediction_json(self, stable_pipeline):
        """Engine should write prediction data that hub can read."""
        result = stable_pipeline["result"]
        predictions = result["predictions"]
        assert predictions is not None, "Engine should produce predictions"

    def test_engine_output_scores_serializable(self, stable_pipeline):
        """Engine scores should be JSON-serializable (hub reads as JSON)."""
        scores = stable_pipeline["result"]["scores"]
        serialized = json.dumps(scores)
        deserialized = json.loads(serialized)
        assert deserialized["overall"] == scores["overall"]

    def test_baselines_structure_valid(self, stable_pipeline):
        """Baselines should be in the format Intelligence module expects."""
        baselines = stable_pipeline["result"]["baselines"]
        assert isinstance(baselines, dict), "Baselines should be a dict"
        assert len(baselines) > 0, "Baselines should not be empty"


class TestCachePersistence:
    """Hub cache constants and categories should be properly defined."""

    def test_cache_categories_defined(self):
        """All expected cache category constants should exist."""
        from aria.hub.constants import (
            CACHE_ACTIVITY_LOG,
            CACHE_ACTIVITY_SUMMARY,
            CACHE_PRESENCE,
        )

        assert CACHE_ACTIVITY_LOG == "activity_log"
        assert CACHE_ACTIVITY_SUMMARY == "activity_summary"
        assert CACHE_PRESENCE == "presence"

    def test_prediction_data_json_roundtrip(self, stable_pipeline):
        """Prediction data should survive JSON serialization."""
        predictions = stable_pipeline["result"]["predictions"]
        roundtripped = json.loads(json.dumps(predictions))
        # All keys should survive
        for key in predictions:
            assert key in roundtripped, f"Key {key} lost in JSON roundtrip"


def _make_api_hub():
    """Create a mock IntelligenceHub suitable for create_api."""
    mock_hub = MagicMock(spec=IntelligenceHub)
    mock_hub.cache = MagicMock()
    mock_hub.modules = {}
    mock_hub.module_status = {}
    mock_hub.subscribers = {}
    mock_hub.subscribe = MagicMock()
    mock_hub._request_count = 0
    mock_hub.get_uptime_seconds = MagicMock(return_value=0)
    mock_hub.health_check = AsyncMock(return_value={"status": "ok", "modules": {}})
    return mock_hub


class TestWebSocketAndAPI:
    """API should expose WebSocket and health endpoints."""

    def test_api_has_websocket_route(self):
        """API should include a /ws endpoint."""
        hub = _make_api_hub()
        app = create_api(hub)
        route_paths = [r.path for r in app.routes]
        assert "/ws" in route_paths, f"Should have /ws route, found: {route_paths}"

    def test_health_endpoint_responds(self):
        """Health endpoint should respond with 200."""
        hub = _make_api_hub()
        app = create_api(hub)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
