"""Tests for FaceEmbeddingStore — SQLite CRUD for embeddings and review queue."""

import sqlite3

import numpy as np
import pytest

from aria.faces.store import FaceEmbeddingStore


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
        from contextlib import closing as _closing

        with _closing(sqlite3.connect(store.db_path)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
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
            person_name="justin",
            embedding=embedding,
            event_id="evt-001",
            image_path="/tmp/test.jpg",
            confidence=0.92,
            source="bootstrap",
            verified=True,
        )
        embeddings = store.get_embeddings_for_person("justin")
        assert len(embeddings) == 1
        assert embeddings[0]["person_name"] == "justin"
        np.testing.assert_allclose(embeddings[0]["embedding"], embedding, rtol=1e-5)

    def test_get_all_named_embeddings(self, store):
        """Returns all embeddings with non-null person_name."""
        for i, name in enumerate(["justin", "justin", "carter"]):
            store.add_embedding(
                name, np.random.rand(512).astype(np.float32), f"evt-{i}", f"/tmp/x{i}.jpg", 0.9, "bootstrap", True
            )
        store.add_embedding(
            None, np.random.rand(512).astype(np.float32), "evt-live-1", "/tmp/y.jpg", 0.5, "live", False
        )
        all_named = store.get_all_named_embeddings()
        assert len(all_named) == 3
        assert all(e["person_name"] is not None for e in all_named)

    def test_get_known_people(self, store):
        """Returns list of unique person names with counts."""
        for i in range(3):
            store.add_embedding(
                "justin", np.random.rand(512).astype(np.float32), f"evt-j{i}", f"/tmp/x{i}.jpg", 0.9, "bootstrap", True
            )
        store.add_embedding(
            "carter", np.random.rand(512).astype(np.float32), "evt-c0", "/tmp/y.jpg", 0.9, "bootstrap", True
        )
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

    def test_get_queue_depth(self, store):
        """queue_depth counts only unreviewed items."""
        assert store.get_queue_depth() == 0
        for i in range(3):
            store.add_to_review_queue(f"evt-{i}", "/tmp/x.jpg", np.random.rand(512).astype(np.float32), [], 0.5)
        assert store.get_queue_depth() == 3
        item = store.get_review_queue(limit=1)[0]
        store.mark_reviewed(item["id"], person_name="justin")
        assert store.get_queue_depth() == 2


class TestLiveEventUniqueness:
    def test_duplicate_live_event_raises_integrity_error(self, store):
        """Inserting two live embeddings with the same event_id raises IntegrityError."""
        import sqlite3

        vec = np.random.rand(512).astype(np.float32)
        store.add_embedding("justin", vec, "evt-dup", "/tmp/a.jpg", 0.9, "live", False)
        with pytest.raises(sqlite3.IntegrityError):
            store.add_embedding("justin", vec, "evt-dup", "/tmp/b.jpg", 0.9, "live", False)

    def test_duplicate_bootstrap_event_raises_integrity_error(self, store):
        """Bootstrap embeddings with same event_id raise IntegrityError (prevents re-run doubling)."""
        vec = np.random.rand(512).astype(np.float32)
        store.add_embedding("justin", vec.copy(), "bs_abc123", "/tmp/a.jpg", 0.0, "bootstrap", False)
        with pytest.raises(sqlite3.IntegrityError):
            store.add_embedding("justin", vec.copy(), "bs_abc123", "/tmp/b.jpg", 0.0, "bootstrap", False)
