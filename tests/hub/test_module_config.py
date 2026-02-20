"""Tests for module source configuration endpoints."""

from unittest.mock import AsyncMock


class TestGetModuleSources:
    def test_get_module_sources_returns_config_value(self, api_hub, api_client):
        """GET returns parsed comma-separated sources from config."""
        api_hub.cache.get_config = AsyncMock(
            return_value={"key": "presence.enabled_signals", "value": "camera_person,motion,door", "source": "user"}
        )

        response = api_client.get("/api/config/modules/presence/sources")
        assert response.status_code == 200

        data = response.json()
        assert data["module"] == "presence"
        assert data["sources"] == ["camera_person", "motion", "door"]
        assert data["config_key"] == "presence.enabled_signals"

    def test_get_module_sources_empty_config(self, api_hub, api_client):
        """GET returns empty list when config value is empty or missing."""
        api_hub.cache.get_config = AsyncMock(return_value=None)

        response = api_client.get("/api/config/modules/activity/sources")
        assert response.status_code == 200

        data = response.json()
        assert data["sources"] == []

    def test_get_module_sources_unknown_module_returns_404(self, api_hub, api_client):
        """GET with unknown module name returns 404."""
        response = api_client.get("/api/config/modules/nonexistent/sources")
        assert response.status_code == 404


class TestPutModuleSources:
    def test_put_module_sources_updates_config(self, api_hub, api_client):
        """PUT calls set_config with comma-separated value."""
        api_hub.cache.set_config = AsyncMock(return_value={"key": "activity.enabled_domains", "value": "light,switch"})

        response = api_client.put(
            "/api/config/modules/activity/sources",
            json={"sources": ["light", "switch"]},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["module"] == "activity"
        assert data["sources"] == ["light", "switch"]
        assert data["config_key"] == "activity.enabled_domains"

        api_hub.cache.set_config.assert_called_once_with("activity.enabled_domains", "light,switch", changed_by="user")

    def test_put_module_sources_empty_returns_400(self, api_hub, api_client):
        """PUT with empty sources list returns 400."""
        response = api_client.put(
            "/api/config/modules/presence/sources",
            json={"sources": []},
        )
        assert response.status_code == 400

    def test_put_module_sources_unknown_module_returns_404(self, api_hub, api_client):
        """PUT to unknown module returns 404."""
        response = api_client.put(
            "/api/config/modules/nonexistent/sources",
            json={"sources": ["something"]},
        )
        assert response.status_code == 404
