"""Tests for /api/faces/* endpoints."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from aria.faces.store import FaceEmbeddingStore
from aria.hub.api import create_api
from aria.hub.core import IntelligenceHub


@pytest.fixture
def faces_store(tmp_path):
    s = FaceEmbeddingStore(str(tmp_path / "faces.db"))
    s.initialize()
    return s


@pytest.fixture
def api_hub(faces_store):
    mock_hub = MagicMock(spec=IntelligenceHub)
    mock_hub.cache = MagicMock()
    mock_hub.modules = {}
    mock_hub.module_status = {}
    mock_hub.subscribers = {}
    mock_hub.subscribe = MagicMock()
    mock_hub._request_count = 0
    mock_hub._audit_logger = None
    mock_hub.set_cache = AsyncMock()
    mock_hub.get_uptime_seconds = MagicMock(return_value=0)
    mock_hub.faces_store = faces_store
    return mock_hub


@pytest.fixture
def api_client(api_hub):
    app = create_api(api_hub)
    return TestClient(app)


class TestFacesQueueAPI:
    def test_get_queue_empty(self, api_client):
        response = api_client.get("/api/faces/queue")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["depth"] == 0

    def test_label_queued_face(self, api_client, api_hub):
        """POST /api/faces/label marks item reviewed and saves embedding."""
        vec = np.random.rand(512).astype(np.float32)
        qid = api_hub.faces_store.add_to_review_queue("evt-001", "/tmp/face.jpg", vec, [], 0.8)
        response = api_client.post(
            "/api/faces/label",
            json={
                "queue_id": qid,
                "person_name": "justin",
            },
        )
        assert response.status_code == 200
        assert api_hub.faces_store.get_queue_depth() == 0
        embeddings = api_hub.faces_store.get_embeddings_for_person("justin")
        assert len(embeddings) == 1


class TestFacesPeopleAPI:
    def test_get_people_empty(self, api_client):
        response = api_client.get("/api/faces/people")
        assert response.status_code == 200
        assert response.json()["people"] == []

    def test_get_people_with_data(self, api_client, api_hub):
        for _ in range(3):
            api_hub.faces_store.add_embedding(
                "justin", np.random.rand(512).astype(np.float32), "evt", "/tmp/x.jpg", 0.9, "bootstrap", True
            )
        response = api_client.get("/api/faces/people")
        assert response.status_code == 200
        data = response.json()
        assert len(data["people"]) == 1
        assert data["people"][0]["person_name"] == "justin"
        assert data["people"][0]["count"] == 3


class TestFacesStatsAPI:
    def test_get_stats(self, api_client):
        response = api_client.get("/api/faces/stats")
        assert response.status_code == 200
        data = response.json()
        assert "queue_depth" in data
        assert "known_people" in data
