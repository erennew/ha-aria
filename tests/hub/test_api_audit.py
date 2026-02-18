"""Tests for /api/audit/* endpoints and request middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from aria.hub.api import create_api
from aria.hub.audit import AuditLogger


@pytest.fixture
async def audit_logger(tmp_path):
    al = AuditLogger()
    await al.initialize(str(tmp_path / "audit.db"))
    yield al
    await al.shutdown()


@pytest.fixture
def mock_hub(audit_logger):
    hub = MagicMock()
    hub.cache = MagicMock()
    hub.modules = {}
    hub.subscribers = {}
    hub.subscribe = MagicMock()
    hub._request_count = 0
    hub._audit_logger = audit_logger
    hub.get_uptime_seconds = MagicMock(return_value=0)
    hub.get_module = MagicMock(return_value=None)
    hub.get_cache = AsyncMock(return_value=None)
    return hub


@pytest.fixture
def client(mock_hub):
    app = create_api(mock_hub)
    return TestClient(app)


class TestRequestMiddleware:
    def test_request_id_header_present(self, client):
        resp = client.get("/")
        assert "X-Request-ID" in resp.headers
        # UUID format check
        rid = resp.headers["X-Request-ID"]
        assert len(rid) == 36  # UUID string length


class TestAuditEventsEndpoint:
    def test_get_events_empty(self, client):
        resp = client.get("/api/audit/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data

    def test_get_events_with_filters(self, client):
        resp = client.get("/api/audit/events?type=cache.write&severity=error&limit=10")
        assert resp.status_code == 200


class TestAuditRequestsEndpoint:
    def test_get_requests(self, client):
        resp = client.get("/api/audit/requests")
        assert resp.status_code == 200


class TestAuditStatsEndpoint:
    def test_get_stats(self, client):
        resp = client.get("/api/audit/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_events" in data


class TestAuditStartupsEndpoint:
    def test_get_startups(self, client):
        resp = client.get("/api/audit/startups")
        assert resp.status_code == 200


class TestAuditIntegrityEndpoint:
    def test_verify_integrity(self, client):
        resp = client.get("/api/audit/integrity")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "valid" in data


class TestAuditWithoutLogger:
    def test_events_without_logger(self):
        """Endpoints return empty results when no audit logger attached."""
        hub = MagicMock()
        hub.cache = MagicMock()
        hub.modules = {}
        hub.subscribers = {}
        hub.subscribe = MagicMock()
        hub._request_count = 0
        hub._audit_logger = None
        hub.get_uptime_seconds = MagicMock(return_value=0)
        hub.get_module = MagicMock(return_value=None)
        hub.get_cache = AsyncMock(return_value=None)
        app = create_api(hub)
        client = TestClient(app)
        resp = client.get("/api/audit/events")
        assert resp.status_code == 200
        assert resp.json()["events"] == []
