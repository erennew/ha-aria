"""Tests for API fixes — can-predict cache bypass (#27), trend direction (#C5)."""

from unittest.mock import AsyncMock

from aria.hub.api import _compute_stage_health

# ============================================================================
# #27: Toggle can-predict uses hub.set_cache (not hub.cache.set)
# ============================================================================


class TestToggleCanPredictCacheBypass:
    """PUT /api/capabilities/{name}/can-predict must use hub.set_cache for WS notifications."""

    def test_toggle_can_predict_uses_hub_set_cache(self, api_hub, api_client):
        """Toggle can_predict calls hub.set_cache (not hub.cache.set)."""
        # Set up mock: capabilities exist with a test capability
        api_hub.cache.get = AsyncMock(
            return_value={
                "data": {
                    "lighting": {
                        "status": "promoted",
                        "can_predict": False,
                    }
                }
            }
        )
        api_hub.set_cache = AsyncMock(return_value=1)

        response = api_client.put(
            "/api/capabilities/lighting/can-predict",
            json={"can_predict": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["capability"] == "lighting"
        assert data["can_predict"] is True

        # The key assertion: hub.set_cache was called (not hub.cache.set)
        api_hub.set_cache.assert_awaited_once()
        call_args = api_hub.set_cache.call_args
        assert call_args[0][0] == "capabilities"  # category
        assert call_args[0][1]["lighting"]["can_predict"] is True

    def test_toggle_can_predict_unknown_capability(self, api_hub, api_client):
        """Returns 404 for unknown capability."""
        api_hub.cache.get = AsyncMock(return_value={"data": {"lighting": {"status": "promoted"}}})

        response = api_client.put(
            "/api/capabilities/nonexistent/can-predict",
            json={"can_predict": True},
        )

        assert response.status_code == 404

    def test_toggle_can_predict_no_capabilities(self, api_hub, api_client):
        """Returns 404 when capabilities cache is empty."""
        api_hub.cache.get = AsyncMock(return_value=None)

        response = api_client.put(
            "/api/capabilities/lighting/can-predict",
            json={"can_predict": True},
        )

        assert response.status_code == 404

    def test_toggle_can_predict_invalid_value(self, api_hub, api_client):
        """Returns 400 when can_predict is not a boolean."""
        api_hub.cache.get = AsyncMock(return_value={"data": {"lighting": {"status": "promoted"}}})

        response = api_client.put(
            "/api/capabilities/lighting/can-predict",
            json={"can_predict": "yes"},
        )

        assert response.status_code == 400


# ============================================================================
# C5: Trend direction uses 0.02 threshold
# ============================================================================


class TestTrendDirectionThreshold:
    """_compute_stage_health trend_direction uses 0.02 delta threshold."""

    def test_small_delta_is_stable(self):
        """A delta of 0.01 (below 0.02 threshold) should be 'stable'."""
        stats = {
            "total_resolved": 100,
            "total_correct": 70,
            "total_attempted": 100,
            "predictions": [{"confidence": 0.7, "correct": True}] * 70 + [{"confidence": 0.3, "correct": False}] * 30,
            "daily_trend": [{"accuracy": 0.70} for _ in range(3)] + [{"accuracy": 0.71} for _ in range(3)],
        }
        result = _compute_stage_health(stats)
        assert result["trend_direction"] == "stable"

    def test_large_positive_delta_is_improving(self):
        """A delta > 0.02 should be 'improving'."""
        stats = {
            "total_resolved": 100,
            "total_correct": 70,
            "total_attempted": 100,
            "predictions": [{"confidence": 0.7, "correct": True}] * 70 + [{"confidence": 0.3, "correct": False}] * 30,
            "daily_trend": [{"accuracy": 0.60} for _ in range(3)] + [{"accuracy": 0.70} for _ in range(3)],
        }
        result = _compute_stage_health(stats)
        assert result["trend_direction"] == "improving"

    def test_large_negative_delta_is_degrading(self):
        """A delta < -0.02 should be 'degrading'."""
        stats = {
            "total_resolved": 100,
            "total_correct": 70,
            "total_attempted": 100,
            "predictions": [{"confidence": 0.7, "correct": True}] * 70 + [{"confidence": 0.3, "correct": False}] * 30,
            "daily_trend": [{"accuracy": 0.75} for _ in range(3)] + [{"accuracy": 0.65} for _ in range(3)],
        }
        result = _compute_stage_health(stats)
        assert result["trend_direction"] == "degrading"

    def test_insufficient_data(self):
        """Fewer than 3 trend points should be 'insufficient_data'."""
        stats = {
            "total_resolved": 10,
            "total_correct": 7,
            "total_attempted": 10,
            "predictions": [{"confidence": 0.7, "correct": True}] * 7 + [{"confidence": 0.3, "correct": False}] * 3,
            "daily_trend": [{"accuracy": 0.7}],
        }
        result = _compute_stage_health(stats)
        assert result["trend_direction"] == "insufficient_data"


# ============================================================================
# #292: CORS allow_headers must include Content-Type
# ============================================================================


class TestCORSAllowHeaders:
    """CORS preflight must allow Content-Type and X-API-Key headers."""

    def test_cors_allow_headers_includes_content_type(self, api_hub, api_client):
        """#292: CORS preflight must allow Content-Type header."""
        resp = api_client.options(
            "/api/models/retrain",
            headers={
                "Origin": "http://127.0.0.1:8001",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type,X-API-Key",
            },
        )
        allowed = resp.headers.get("access-control-allow-headers", "")
        assert "content-type" in allowed.lower(), f"Content-Type not in CORS allow_headers: '{allowed}'"

    def test_cors_allow_headers_includes_x_api_key(self, api_hub, api_client):
        """#292 + #267: CORS preflight must allow X-API-Key header."""
        resp = api_client.options(
            "/api/models/retrain",
            headers={
                "Origin": "http://127.0.0.1:8001",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        allowed = resp.headers.get("access-control-allow-headers", "")
        assert "x-api-key" in allowed.lower(), f"X-API-Key not in CORS allow_headers: '{allowed}'"
