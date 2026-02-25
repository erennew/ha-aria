"""Tests for FaceEmbeddingStore — SQLite CRUD for embeddings and review queue."""

import numpy as np
import pytest

from aria.faces.store import EmbeddingRecord, FaceEmbeddingStore

_REC_DEFAULTS = {
    "event_id": "evt",
    "image_path": "/tmp/x.jpg",
    "confidence": 0.9,
    "source": "bootstrap",
    "verified": True,
}


def _rec(person_name, embedding, **overrides):
    """Helper: build an EmbeddingRecord with defaults."""
    fields = {**_REC_DEFAULTS, **overrides}
    return EmbeddingRecord(person_name=person_name, embedding=embedding, **fields)


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "faces_test.db")
    s = FaceEmbeddingStore(db_path)
    s.initialize()
    return s


class TestFaceEmbeddingStoreSchema:
    def test_initializes_tables(self, store):
        """Both tables exist after initialize()."""
        import sqlite3

        conn = sqlite3.connect(store.db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "face_embeddings" in tables
        assert "face_review_queue" in tables

    def test_idempotent_initialize(self, store):
        """Calling initialize() twice does not raise."""
        store.initialize()  # second call


class TestFaceEmbeddingStoreCRUD:
    def test_add_and_retrieve_embedding(self, store):
        """Can store and retrieve a named embedding."""
        embedding = np.random.rand(512).astype(np.float32)
        store.add_embedding(
            EmbeddingRecord(
                person_name="justin",
                embedding=embedding,
                event_id="evt-001",
                image_path="/tmp/test.jpg",
                confidence=0.92,
                source="bootstrap",
                verified=True,
            )
        )
        embeddings = store.get_embeddings_for_person("justin")
        assert len(embeddings) == 1
        assert embeddings[0]["person_name"] == "justin"
        np.testing.assert_allclose(embeddings[0]["embedding"], embedding, rtol=1e-5)

    def test_get_all_named_embeddings(self, store):
        """Returns all embeddings with non-null person_name."""
        for name in ["justin", "justin", "carter"]:
            store.add_embedding(_rec(name, np.random.rand(512).astype(np.float32)))
        store.add_embedding(
            _rec(None, np.random.rand(512).astype(np.float32), confidence=0.5, source="live", verified=False)
        )
        all_named = store.get_all_named_embeddings()
        assert len(all_named) == 3
        assert all(e["person_name"] is not None for e in all_named)

    def test_get_known_people(self, store):
        """Returns list of unique person names with counts."""
        for _ in range(3):
            store.add_embedding(_rec("justin", np.random.rand(512).astype(np.float32)))
        store.add_embedding(_rec("carter", np.random.rand(512).astype(np.float32), image_path="/tmp/y.jpg"))
        people = store.get_known_people()
        names = {p["person_name"] for p in people}
        assert names == {"justin", "carter"}
        justin = next(p for p in people if p["person_name"] == "justin")
        assert justin["count"] == 3


class TestAdaptiveThreshold:
    def test_threshold_decreases_with_sample_count(self, store):
        """Threshold tightens as labeled sample count grows."""
        t5 = store.get_threshold_for_person("justin", labeled_count=5)
        t50 = store.get_threshold_for_person("justin", labeled_count=50)
        t100 = store.get_threshold_for_person("justin", labeled_count=100)
        assert t5 > t50 > t100

    def test_threshold_floor(self, store):
        """Threshold never drops below 0.50."""
        t = store.get_threshold_for_person("justin", labeled_count=10000)
        assert t >= 0.50

    def test_threshold_ceiling(self, store):
        """Threshold never exceeds 0.85 for any count."""
        t = store.get_threshold_for_person("new_person", labeled_count=0)
        assert t <= 0.85


class TestReviewQueue:
    def test_add_to_queue(self, store):
        """Can add a face to the review queue."""
        embedding = np.random.rand(512).astype(np.float32)
        candidates = [{"name": "justin", "confidence": 0.72}]
        store.add_to_review_queue(
            event_id="evt-002",
            image_path="/tmp/face.jpg",
            embedding=embedding,
            top_candidates=candidates,
            priority=1.0 - 0.72,
        )
        queue = store.get_review_queue(limit=10)
        assert len(queue) == 1
        assert queue[0]["event_id"] == "evt-002"
        assert queue[0]["top_candidates"][0]["name"] == "justin"

    def test_queue_sorted_by_priority(self, store):
        """Queue returns highest-priority (most uncertain) items first."""
        for priority in [0.1, 0.9, 0.5]:
            store.add_to_review_queue("evt", "/tmp/x.jpg", np.random.rand(512).astype(np.float32), [], priority)
        queue = store.get_review_queue(limit=10)
        priorities = [q["priority"] for q in queue]
        assert priorities == sorted(priorities, reverse=True)

    def test_mark_reviewed(self, store):
        """Reviewed items no longer appear in queue."""
        store.add_to_review_queue("evt-003", "/tmp/face.jpg", np.random.rand(512).astype(np.float32), [], 0.8)
        item = store.get_review_queue(limit=1)[0]
        store.mark_reviewed(item["id"], person_name="justin")
        queue = store.get_review_queue(limit=10)
        assert len(queue) == 0
