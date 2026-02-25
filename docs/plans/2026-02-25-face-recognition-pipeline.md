# Face Recognition Presence Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a closed-loop face recognition pipeline that bootstraps from existing Frigate footage, continuously improves via active learning, and drives ARIA presence detection — making labeling an outlier activity within weeks.

**Architecture:** Extend `aria/modules/presence.py` with a DeepFace/FaceNet512 embedding store (new `aria/faces/` module) and adaptive per-person confidence thresholds. Bootstrap clusters 2,896 existing snapshots via DBSCAN. Live pipeline intercepts Frigate MQTT events — auto-labels high-confidence matches, queues low-confidence for review via new ARIA UI Faces page.

**Tech Stack:** DeepFace (FaceNet512 backend), scikit-learn (DBSCAN), SQLite (`faces.db`), FastAPI, Preact/JSX

**Design doc:** `docs/plans/2026-02-25-face-recognition-presence-design.md`
**Research:** `tasks/research-face-recognition.md`

---

## Pre-Flight

```bash
# Work from ha-aria project root
cd ~/Documents/projects/ha-aria

# Verify ARIA is running (needed for manual testing later)
curl -s http://127.0.0.1:8001/api/cache | python3 -m json.tool | head -5

# Check test suite is green before starting
python3 -m pytest tests/ -x -q --timeout=120 2>&1 | tail -5

# faces.db will live alongside hub.db
ls ~/ha-logs/intelligence/cache/
```

---

## Task 1: Install DeepFace + create `aria/faces/` skeleton

**Files:**
- Create: `aria/faces/__init__.py`
- Create: `aria/faces/store.py` (stub)
- Create: `aria/faces/extractor.py` (stub)
- Create: `aria/faces/bootstrap.py` (stub)
- Create: `aria/faces/pipeline.py` (stub)
- Create: `tests/hub/test_faces_store.py` (stub)

**Step 1: Install deepface**

```bash
pip install deepface>=0.0.93
# Verify — downloads FaceNet512 weights (~600MB) on first use, not install
python3 -c "import deepface; print(deepface.__version__)"
```

**Step 2: Create module skeleton**

```bash
mkdir -p aria/faces
```

`aria/faces/__init__.py`:
```python
"""Face recognition pipeline for ARIA presence detection."""
```

`aria/faces/store.py`:
```python
"""Face embedding store — SQLite CRUD for embeddings and review queue."""
```

`aria/faces/extractor.py`:
```python
"""DeepFace wrapper for face detection and embedding extraction."""
```

`aria/faces/bootstrap.py`:
```python
"""Bootstrap pipeline: batch-process Frigate clips → DBSCAN clusters."""
```

`aria/faces/pipeline.py`:
```python
"""Live face pipeline: Frigate event → embed → match → auto-label or queue."""
```

**Step 3: Verify imports work**

```bash
python3 -c "from aria.faces import store, extractor, bootstrap, pipeline; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add aria/faces/
git commit -m "feat: scaffold aria/faces/ module — face recognition pipeline skeleton"
```

---

## Task 2: FaceEmbeddingStore — SQLite schema + CRUD

**Files:**
- Modify: `aria/faces/store.py`
- Create: `tests/hub/test_faces_store.py`

**Step 1: Write failing tests**

`tests/hub/test_faces_store.py`:
```python
"""Tests for FaceEmbeddingStore — SQLite CRUD for embeddings and review queue."""

import tempfile
import numpy as np
import pytest
from pathlib import Path

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
        for name in ["justin", "justin", "carter"]:
            store.add_embedding(name, np.random.rand(512).astype(np.float32),
                                "evt", "/tmp/x.jpg", 0.9, "bootstrap", True)
        store.add_embedding(None, np.random.rand(512).astype(np.float32),
                            "evt", "/tmp/y.jpg", 0.5, "live", False)
        all_named = store.get_all_named_embeddings()
        assert len(all_named) == 3
        assert all(e["person_name"] is not None for e in all_named)

    def test_get_known_people(self, store):
        """Returns list of unique person names with counts."""
        for _ in range(3):
            store.add_embedding("justin", np.random.rand(512).astype(np.float32),
                                "evt", "/tmp/x.jpg", 0.9, "bootstrap", True)
        store.add_embedding("carter", np.random.rand(512).astype(np.float32),
                            "evt", "/tmp/y.jpg", 0.9, "bootstrap", True)
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
            store.add_to_review_queue("evt", "/tmp/x.jpg",
                                      np.random.rand(512).astype(np.float32),
                                      [], priority)
        queue = store.get_review_queue(limit=10)
        priorities = [q["priority"] for q in queue]
        assert priorities == sorted(priorities, reverse=True)

    def test_mark_reviewed(self, store):
        """Reviewed items no longer appear in queue."""
        store.add_to_review_queue("evt-003", "/tmp/face.jpg",
                                  np.random.rand(512).astype(np.float32),
                                  [], 0.8)
        item = store.get_review_queue(limit=1)[0]
        store.mark_reviewed(item["id"], person_name="justin")
        queue = store.get_review_queue(limit=10)
        assert len(queue) == 0
```

**Step 2: Run — verify all fail**

```bash
python3 -m pytest tests/hub/test_faces_store.py -v --timeout=30 2>&1 | tail -15
```
Expected: all FAIL with `ImportError` or `AttributeError`

**Step 3: Implement FaceEmbeddingStore**

`aria/faces/store.py`:
```python
"""Face embedding store — SQLite CRUD for embeddings and review queue."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


class FaceEmbeddingStore:
    """SQLite-backed store for face embeddings and review queue."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Create tables if they don't exist. Idempotent."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS face_embeddings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_name TEXT,
                    embedding   BLOB NOT NULL,
                    event_id    TEXT,
                    image_path  TEXT,
                    confidence  REAL,
                    source      TEXT NOT NULL,
                    verified    INTEGER DEFAULT 0,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS face_review_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id        TEXT NOT NULL,
                    image_path      TEXT NOT NULL,
                    embedding       BLOB NOT NULL,
                    top_candidates  TEXT,
                    priority        REAL DEFAULT 0.5,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at     DATETIME,
                    person_name     TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_embeddings_person
                    ON face_embeddings(person_name);
                CREATE INDEX IF NOT EXISTS idx_queue_priority
                    ON face_review_queue(priority DESC, reviewed_at);
            """)
            conn.commit()

    # --- Embeddings ---

    def add_embedding(
        self,
        person_name: str | None,
        embedding: np.ndarray,
        event_id: str,
        image_path: str,
        confidence: float,
        source: str,
        verified: bool = False,
    ) -> int:
        blob = embedding.astype(np.float32).tobytes()
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                """INSERT INTO face_embeddings
                   (person_name, embedding, event_id, image_path, confidence, source, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (person_name, blob, event_id, image_path, confidence, source, int(verified)),
            )
            conn.commit()
            return cur.lastrowid

    def get_embeddings_for_person(self, person_name: str) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM face_embeddings WHERE person_name = ?",
                (person_name,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_all_named_embeddings(self) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM face_embeddings WHERE person_name IS NOT NULL"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_known_people(self) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """SELECT person_name, COUNT(*) as count
                   FROM face_embeddings
                   WHERE person_name IS NOT NULL
                   GROUP BY person_name
                   ORDER BY count DESC"""
            ).fetchall()
        return [{"person_name": r[0], "count": r[1]} for r in rows]

    # --- Adaptive threshold ---

    @staticmethod
    def get_threshold_for_person(_person_name: str, labeled_count: int) -> float:
        """Per-person adaptive threshold — tightens as sample count grows.

        Formula from arxiv 1810.11160 (+22% accuracy vs fixed threshold).
        """
        return max(0.50, 0.85 - (0.005 * labeled_count))

    # --- Review queue ---

    def add_to_review_queue(
        self,
        event_id: str,
        image_path: str,
        embedding: np.ndarray,
        top_candidates: list[dict],
        priority: float,
    ) -> int:
        blob = embedding.astype(np.float32).tobytes()
        candidates_json = json.dumps(top_candidates)
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                """INSERT INTO face_review_queue
                   (event_id, image_path, embedding, top_candidates, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, image_path, blob, candidates_json, priority),
            )
            conn.commit()
            return cur.lastrowid

    def get_review_queue(self, limit: int = 20) -> list[dict]:
        """Return pending queue items, highest priority first."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM face_review_queue
                   WHERE reviewed_at IS NULL
                   ORDER BY priority DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["top_candidates"] = json.loads(d["top_candidates"] or "[]")
            d["embedding"] = np.frombuffer(d["embedding"], dtype=np.float32)
            result.append(d)
        return result

    def mark_reviewed(self, queue_id: int, person_name: str | None = None) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """UPDATE face_review_queue
                   SET reviewed_at = ?, person_name = ?
                   WHERE id = ?""",
                (datetime.utcnow().isoformat(), person_name, queue_id),
            )
            conn.commit()

    def get_queue_depth(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM face_review_queue WHERE reviewed_at IS NULL"
            ).fetchone()[0]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if "embedding" in d and d["embedding"]:
        d["embedding"] = np.frombuffer(d["embedding"], dtype=np.float32)
    return d
```

**Step 4: Run tests — all pass**

```bash
python3 -m pytest tests/hub/test_faces_store.py -v --timeout=30
```
Expected: all PASS

**Step 5: Commit**

```bash
git add aria/faces/store.py tests/hub/test_faces_store.py
git commit -m "feat: add FaceEmbeddingStore — SQLite schema, CRUD, adaptive thresholds, review queue"
```

---

## Task 3: DeepFace extractor wrapper

**Files:**
- Modify: `aria/faces/extractor.py`
- Create: `tests/hub/test_faces_extractor.py`

**Step 1: Write failing tests**

`tests/hub/test_faces_extractor.py`:
```python
"""Tests for FaceExtractor — DeepFace wrapper."""

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from aria.faces.extractor import FaceExtractor


class TestFaceExtractorEmbedding:
    def test_returns_numpy_array(self):
        """extract_embedding returns 512-d float32 array."""
        extractor = FaceExtractor()
        fake_result = [{"embedding": list(np.random.rand(512))}]
        with patch("aria.faces.extractor.DeepFace.represent", return_value=fake_result):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is not None
        assert result.shape == (512,)
        assert result.dtype == np.float32

    def test_returns_none_on_no_face(self):
        """Returns None when DeepFace finds no face."""
        extractor = FaceExtractor()
        with patch("aria.faces.extractor.DeepFace.represent", side_effect=ValueError("No face")):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is None

    def test_returns_none_on_exception(self):
        """Returns None (not raise) on unexpected errors — silent failure prevention."""
        extractor = FaceExtractor()
        with patch("aria.faces.extractor.DeepFace.represent", side_effect=Exception("GPU OOM")):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is None

    def test_cosine_similarity(self):
        """cosine_similarity returns 1.0 for identical vectors."""
        extractor = FaceExtractor()
        v = np.random.rand(512).astype(np.float32)
        assert abs(extractor.cosine_similarity(v, v) - 1.0) < 1e-5

    def test_cosine_similarity_orthogonal(self):
        """cosine_similarity returns 0.0 for orthogonal vectors."""
        extractor = FaceExtractor()
        a = np.zeros(512, dtype=np.float32)
        b = np.zeros(512, dtype=np.float32)
        a[0] = 1.0
        b[1] = 1.0
        assert abs(extractor.cosine_similarity(a, b)) < 1e-5

    def test_find_best_match_returns_top_candidates(self):
        """find_best_match returns sorted candidates above min threshold."""
        extractor = FaceExtractor()
        query = np.ones(512, dtype=np.float32)
        query /= np.linalg.norm(query)

        named = [
            {"person_name": "justin", "embedding": query.copy()},  # perfect match
            {"person_name": "carter", "embedding": -query.copy()}, # opposite
        ]
        candidates = extractor.find_best_match(query, named, min_threshold=0.0)
        assert candidates[0]["person_name"] == "justin"
        assert candidates[0]["confidence"] > 0.99
        assert candidates[1]["confidence"] < candidates[0]["confidence"]
```

**Step 2: Run — verify all fail**

```bash
python3 -m pytest tests/hub/test_faces_extractor.py -v --timeout=30 2>&1 | tail -10
```

**Step 3: Implement FaceExtractor**

`aria/faces/extractor.py`:
```python
"""DeepFace wrapper for face detection and embedding extraction."""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Lazy import — DeepFace downloads ~600MB on first use
# Import at call time, not module load
_deepface = None


def _get_deepface():
    global _deepface
    if _deepface is None:
        from deepface import DeepFace  # noqa: PLC0415
        _deepface = DeepFace
    return _deepface


class FaceExtractor:
    """Extract 512-d FaceNet512 embeddings from image files."""

    MODEL = "Facenet512"
    DETECTOR = "retinaface"  # Best detector for surveillance footage

    def extract_embedding(self, image_path: str) -> np.ndarray | None:
        """Return 512-d float32 embedding, or None if no face detected."""
        try:
            DeepFace = _get_deepface()
            result = DeepFace.represent(
                img_path=image_path,
                model_name=self.MODEL,
                detector_backend=self.DETECTOR,
                enforce_detection=True,
            )
            if not result:
                return None
            vec = np.array(result[0]["embedding"], dtype=np.float32)
            return vec / np.linalg.norm(vec)  # L2 normalize
        except ValueError:
            # No face detected — expected for many snapshots
            return None
        except Exception:
            logger.exception("FaceExtractor: unexpected error on %s", image_path)
            return None

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalized vectors."""
        return float(np.dot(a, b))

    def find_best_match(
        self,
        query: np.ndarray,
        named_embeddings: list[dict],
        min_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Compare query against named embeddings, return sorted candidates.

        Args:
            query: 512-d normalized embedding to match
            named_embeddings: list of {person_name, embedding} dicts
            min_threshold: discard candidates below this confidence

        Returns:
            List of {person_name, confidence} sorted by confidence desc
        """
        scores: dict[str, list[float]] = {}
        for entry in named_embeddings:
            name = entry["person_name"]
            sim = self.cosine_similarity(query, entry["embedding"])
            scores.setdefault(name, []).append(sim)

        # Average similarity per person (robust to outliers)
        candidates = [
            {"person_name": name, "confidence": float(np.mean(sims))}
            for name, sims in scores.items()
            if np.mean(sims) >= min_threshold
        ]
        return sorted(candidates, key=lambda x: x["confidence"], reverse=True)
```

**Step 4: Run tests — all pass**

```bash
python3 -m pytest tests/hub/test_faces_extractor.py -v --timeout=30
```

**Step 5: Commit**

```bash
git add aria/faces/extractor.py tests/hub/test_faces_extractor.py
git commit -m "feat: add FaceExtractor — DeepFace/FaceNet512 wrapper with cosine matching"
```

---

## Task 4: Bootstrap pipeline (batch extract + DBSCAN cluster)

**Files:**
- Modify: `aria/faces/bootstrap.py`
- Create: `tests/hub/test_faces_bootstrap.py`

**Step 1: Write failing tests**

`tests/hub/test_faces_bootstrap.py`:
```python
"""Tests for BootstrapPipeline — batch clip extraction + DBSCAN clustering."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from aria.faces.bootstrap import BootstrapPipeline
from aria.faces.store import FaceEmbeddingStore


@pytest.fixture
def store(tmp_path):
    s = FaceEmbeddingStore(str(tmp_path / "faces.db"))
    s.initialize()
    return s


@pytest.fixture
def pipeline(store):
    return BootstrapPipeline(
        clips_dir="/tmp/fake_clips",
        store=store,
    )


class TestBootstrapPipeline:
    def test_scan_returns_jpg_paths(self, pipeline, tmp_path):
        """scan_clips returns all .jpg files in clips dir."""
        clips = tmp_path / "clips"
        clips.mkdir()
        (clips / "backyard-001.jpg").touch()
        (clips / "backyard-002.jpg").touch()
        (clips / "backyard-001-clean.png").touch()  # exclude PNGs
        pipeline.clips_dir = str(clips)
        paths = pipeline.scan_clips()
        assert len(paths) == 2
        assert all(p.endswith(".jpg") for p in paths)

    def test_cluster_embeddings_groups_similar(self, pipeline):
        """DBSCAN clusters near-identical embeddings into same cluster."""
        base = np.random.rand(512).astype(np.float32)
        base /= np.linalg.norm(base)
        # Two tight clusters
        cluster_a = [base + np.random.rand(512).astype(np.float32) * 0.01 for _ in range(5)]
        cluster_b = [-base + np.random.rand(512).astype(np.float32) * 0.01 for _ in range(5)]
        embeddings = cluster_a + cluster_b
        for i, e in enumerate(embeddings):
            embeddings[i] = e / np.linalg.norm(e)

        labels = pipeline.cluster_embeddings(embeddings)
        assert len(set(labels)) == 2  # exactly 2 clusters (no noise with tight groups)

    def test_cluster_returns_noise_label(self, pipeline):
        """DBSCAN returns -1 for outlier embeddings."""
        # Single isolated embedding — too far from others to cluster
        embeddings = [np.random.rand(512).astype(np.float32) for _ in range(20)]
        for i, e in enumerate(embeddings):
            embeddings[i] = e / np.linalg.norm(e)
        labels = pipeline.cluster_embeddings(embeddings)
        # With random embeddings, some should be noise (-1)
        assert -1 in labels

    def test_build_clusters_dict(self, pipeline):
        """build_clusters groups image paths by cluster label."""
        paths = ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
        labels = [0, 0, 1, -1]  # -1 = noise
        clusters = pipeline.build_clusters(paths, labels)
        assert len(clusters["cluster_0"]) == 2
        assert len(clusters["cluster_1"]) == 1
        assert "unknown" in clusters
        assert len(clusters["unknown"]) == 1
```

**Step 2: Run — verify all fail**

```bash
python3 -m pytest tests/hub/test_faces_bootstrap.py -v --timeout=30 2>&1 | tail -10
```

**Step 3: Implement BootstrapPipeline**

`aria/faces/bootstrap.py`:
```python
"""Bootstrap pipeline: batch-process Frigate clips → DBSCAN clusters."""

import logging
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN

from aria.faces.extractor import FaceExtractor
from aria.faces.store import FaceEmbeddingStore

logger = logging.getLogger(__name__)

# DBSCAN params tuned for FaceNet512 cosine distance
# eps=0.4 means faces within cosine distance 0.4 group together
# min_samples=2 means at least 2 images to form a cluster
DBSCAN_EPS = 0.4
DBSCAN_MIN_SAMPLES = 2


class BootstrapPipeline:
    """One-time batch extraction + DBSCAN clustering of Frigate clip snapshots."""

    def __init__(self, clips_dir: str, store: FaceEmbeddingStore):
        self.clips_dir = clips_dir
        self.store = store
        self.extractor = FaceExtractor()

    def scan_clips(self) -> list[str]:
        """Return all .jpg snapshot paths in clips_dir."""
        return sorted(str(p) for p in Path(self.clips_dir).glob("*.jpg"))

    def extract_all(self, image_paths: list[str]) -> tuple[list[str], list[np.ndarray]]:
        """Extract embeddings from all images, skipping failures.

        Returns:
            (valid_paths, embeddings) — only images where a face was detected
        """
        valid_paths, embeddings = [], []
        total = len(image_paths)
        for i, path in enumerate(image_paths):
            if i % 100 == 0:
                logger.info("Bootstrap: %d/%d images processed", i, total)
            embedding = self.extractor.extract_embedding(path)
            if embedding is not None:
                valid_paths.append(path)
                embeddings.append(embedding)
        logger.info("Bootstrap: %d/%d images had detectable faces", len(valid_paths), total)
        return valid_paths, embeddings

    def cluster_embeddings(self, embeddings: list[np.ndarray]) -> list[int]:
        """DBSCAN cluster embeddings by cosine distance.

        Returns list of cluster labels (-1 = noise/unknown).
        """
        matrix = np.stack(embeddings)
        # Cosine distance = 1 - cosine_similarity
        db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES, metric="cosine")
        return db.fit_predict(matrix).tolist()

    def build_clusters(
        self, paths: list[str], labels: list[int]
    ) -> dict[str, list[str]]:
        """Group image paths by cluster label.

        Returns dict: {"cluster_0": [...], "cluster_1": [...], "unknown": [...]}
        """
        clusters: dict[str, list[str]] = {}
        for path, label in zip(paths, labels):
            key = "unknown" if label == -1 else f"cluster_{label}"
            clusters.setdefault(key, []).append(path)
        return clusters

    def run(self) -> dict[str, list[str]]:
        """Execute full bootstrap: scan → extract → cluster.

        Returns cluster dict for UI review.
        Saves all embeddings to store with person_name=None (unidentified).
        """
        logger.info("Bootstrap: scanning %s", self.clips_dir)
        image_paths = self.scan_clips()
        logger.info("Bootstrap: found %d snapshots", len(image_paths))

        valid_paths, embeddings = self.extract_all(image_paths)
        if not embeddings:
            logger.warning("Bootstrap: no faces detected in any snapshots")
            return {}

        labels = self.cluster_embeddings(embeddings)

        # Persist all embeddings as unidentified
        for path, embedding, label in zip(valid_paths, embeddings, labels):
            self.store.add_embedding(
                person_name=None,
                embedding=embedding,
                event_id="bootstrap",
                image_path=path,
                confidence=0.0,
                source="bootstrap",
                verified=False,
            )

        clusters = self.build_clusters(valid_paths, labels)
        logger.info(
            "Bootstrap complete: %d clusters, %d unknown",
            len([k for k in clusters if k != "unknown"]),
            len(clusters.get("unknown", [])),
        )
        return clusters
```

**Step 4: Run tests — all pass**

```bash
python3 -m pytest tests/hub/test_faces_bootstrap.py -v --timeout=60
```

**Step 5: Commit**

```bash
git add aria/faces/bootstrap.py tests/hub/test_faces_bootstrap.py
git commit -m "feat: add BootstrapPipeline — batch DeepFace extraction + DBSCAN clustering"
```

---

## Task 5: Live pipeline (event → embed → match → queue)

**Files:**
- Modify: `aria/faces/pipeline.py`
- Create: `tests/hub/test_faces_pipeline.py`

**Step 1: Write failing tests**

`tests/hub/test_faces_pipeline.py`:
```python
"""Tests for FacePipeline — live event processing."""

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from aria.faces.pipeline import FacePipeline
from aria.faces.store import FaceEmbeddingStore


@pytest.fixture
def store(tmp_path):
    s = FaceEmbeddingStore(str(tmp_path / "faces.db"))
    s.initialize()
    # Seed with one known person
    vec = np.ones(512, dtype=np.float32)
    vec /= np.linalg.norm(vec)
    for _ in range(10):
        s.add_embedding("justin", vec.copy(), "evt", "/tmp/x.jpg", 0.95, "bootstrap", True)
    return s


@pytest.fixture
def pipeline(store):
    return FacePipeline(store=store, frigate_url="http://localhost:5000")


class TestFacePipelineMatching:
    def test_high_confidence_returns_auto_label(self, pipeline):
        """Above threshold returns auto-label result."""
        vec = np.ones(512, dtype=np.float32)
        vec /= np.linalg.norm(vec)

        mock_extractor = MagicMock()
        mock_extractor.extract_embedding.return_value = vec
        mock_extractor.find_best_match.return_value = [
            {"person_name": "justin", "confidence": 0.92}
        ]
        pipeline.extractor = mock_extractor

        result = pipeline.process_embedding(vec, event_id="evt-auto")
        assert result["action"] == "auto_label"
        assert result["person_name"] == "justin"
        assert result["confidence"] >= 0.50

    def test_low_confidence_queues_for_review(self, pipeline):
        """Below threshold adds to review queue."""
        vec = np.ones(512, dtype=np.float32)
        vec /= np.linalg.norm(vec)

        mock_extractor = MagicMock()
        mock_extractor.find_best_match.return_value = [
            {"person_name": "justin", "confidence": 0.30}
        ]
        pipeline.extractor = mock_extractor

        result = pipeline.process_embedding(vec, event_id="evt-queue",
                                            image_path="/tmp/f.jpg")
        assert result["action"] == "queued"
        assert pipeline.store.get_queue_depth() == 1

    def test_no_match_queues_as_unknown(self, pipeline):
        """Empty match list queues as unknown."""
        vec = np.random.rand(512).astype(np.float32)
        mock_extractor = MagicMock()
        mock_extractor.find_best_match.return_value = []
        pipeline.extractor = mock_extractor

        result = pipeline.process_embedding(vec, event_id="evt-unknown",
                                            image_path="/tmp/f.jpg")
        assert result["action"] == "queued"
```

**Step 2: Run — verify fail**

```bash
python3 -m pytest tests/hub/test_faces_pipeline.py -v --timeout=30 2>&1 | tail -10
```

**Step 3: Implement FacePipeline**

`aria/faces/pipeline.py`:
```python
"""Live face pipeline: Frigate event → embed → match → auto-label or queue."""

import logging
from typing import Any

import numpy as np

from aria.faces.extractor import FaceExtractor
from aria.faces.store import FaceEmbeddingStore

logger = logging.getLogger(__name__)


class FacePipeline:
    """Process live Frigate face events — match against store, queue uncertain."""

    def __init__(self, store: FaceEmbeddingStore, frigate_url: str):
        self.store = store
        self.frigate_url = frigate_url
        self.extractor = FaceExtractor()

    def process_embedding(
        self,
        embedding: np.ndarray,
        event_id: str,
        image_path: str = "",
    ) -> dict[str, Any]:
        """Match embedding against known people. Auto-label or queue.

        Returns:
            {"action": "auto_label", "person_name": str, "confidence": float}
            {"action": "queued", "queue_id": int}
            {"action": "skip", "reason": str}
        """
        named = self.store.get_all_named_embeddings()
        if not named:
            # No training data yet — queue everything
            qid = self.store.add_to_review_queue(
                event_id, image_path, embedding, [], priority=1.0
            )
            return {"action": "queued", "queue_id": qid}

        candidates = self.extractor.find_best_match(embedding, named, min_threshold=0.0)
        if not candidates:
            qid = self.store.add_to_review_queue(
                event_id, image_path, embedding, [], priority=1.0
            )
            return {"action": "queued", "queue_id": qid}

        top = candidates[0]
        person_name = top["person_name"]
        confidence = top["confidence"]

        # Get this person's adaptive threshold
        count = sum(1 for e in named if e["person_name"] == person_name)
        threshold = self.store.get_threshold_for_person(person_name, labeled_count=count)

        if confidence >= threshold:
            # Auto-label — save embedding to grow training set
            self.store.add_embedding(
                person_name=person_name,
                embedding=embedding,
                event_id=event_id,
                image_path=image_path,
                confidence=confidence,
                source="live",
                verified=False,
            )
            return {"action": "auto_label", "person_name": person_name, "confidence": confidence}

        # Below threshold — queue for human review
        priority = 1.0 - confidence  # higher uncertainty = higher priority
        qid = self.store.add_to_review_queue(
            event_id, image_path, embedding, candidates[:3], priority
        )
        return {"action": "queued", "queue_id": qid}
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/hub/test_faces_pipeline.py -v --timeout=30
```

**Step 5: Commit**

```bash
git add aria/faces/pipeline.py tests/hub/test_faces_pipeline.py
git commit -m "feat: add FacePipeline — live event matching with adaptive threshold auto-label"
```

---

## Task 6: FastAPI routes for faces

**Files:**
- Create: `aria/hub/routes_faces.py`
- Create: `tests/hub/test_api_faces.py`
- Modify: `aria/hub/api.py` — register face routes

**Step 1: Write failing tests**

`tests/hub/test_api_faces.py`:
```python
"""Tests for /api/faces/* endpoints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from aria.hub.api import create_api
from aria.hub.core import IntelligenceHub
from aria.faces.store import FaceEmbeddingStore


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
        qid = api_hub.faces_store.add_to_review_queue(
            "evt-001", "/tmp/face.jpg", vec, [], 0.8
        )
        response = api_client.post("/api/faces/label", json={
            "queue_id": qid,
            "person_name": "justin",
        })
        assert response.status_code == 200
        # Item should be gone from queue
        assert api_hub.faces_store.get_queue_depth() == 0
        # Embedding saved to store
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
                "justin", np.random.rand(512).astype(np.float32),
                "evt", "/tmp/x.jpg", 0.9, "bootstrap", True
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
```

**Step 2: Run — verify fail**

```bash
python3 -m pytest tests/hub/test_api_faces.py -v --timeout=30 2>&1 | tail -10
```

**Step 3: Implement routes**

`aria/hub/routes_faces.py`:
```python
"""FastAPI routes for face recognition pipeline."""

import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LabelRequest(BaseModel):
    queue_id: int
    person_name: str


def _register_face_routes(router: APIRouter, hub) -> None:
    """Register /api/faces/* endpoints on the router."""

    def _store():
        store = getattr(hub, "faces_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="Face store not initialized")
        return store

    @router.get("/api/faces/queue")
    async def get_face_queue(limit: int = 20):
        """Return pending review queue, highest priority first."""
        try:
            store = _store()
            items = store.get_review_queue(limit=limit)
            # Strip embedding blob from response
            for item in items:
                item.pop("embedding", None)
            return {"items": items, "depth": store.get_queue_depth()}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching face queue")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/label")
    async def label_face(req: LabelRequest):
        """Label a queued face and save embedding to training store."""
        try:
            store = _store()
            queue_items = store.get_review_queue(limit=1000)
            item = next((q for q in queue_items if q["id"] == req.queue_id), None)
            if item is None:
                raise HTTPException(status_code=404, detail="Queue item not found")

            embedding = item["embedding"]
            store.mark_reviewed(req.queue_id, person_name=req.person_name)
            store.add_embedding(
                person_name=req.person_name,
                embedding=embedding,
                event_id=item["event_id"],
                image_path=item["image_path"],
                confidence=1.0,
                source="manual",
                verified=True,
            )
            return {"status": "ok", "person_name": req.person_name}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error labeling face")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.get("/api/faces/people")
    async def get_known_people():
        """Return all known people with embedding counts."""
        try:
            store = _store()
            return {"people": store.get_known_people()}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching known people")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.get("/api/faces/stats")
    async def get_face_stats():
        """Return queue depth and known people count."""
        try:
            store = _store()
            return {
                "queue_depth": store.get_queue_depth(),
                "known_people": len(store.get_known_people()),
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching face stats")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/bootstrap")
    async def trigger_bootstrap():
        """Kick off bootstrap batch extraction (non-blocking)."""
        try:
            import asyncio
            from aria.faces.bootstrap import BootstrapPipeline
            store = _store()
            clips_dir = "/home/justin/frigate/media/clips"

            async def _run():
                pipeline = BootstrapPipeline(clips_dir=clips_dir, store=store)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, pipeline.run)

            asyncio.create_task(_run())
            return {"status": "started", "clips_dir": clips_dir}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error starting bootstrap")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/deploy")
    async def deploy_to_frigate():
        """Copy best N images per person to /media/frigate/faces/<name>/."""
        import shutil
        from pathlib import Path
        try:
            store = _store()
            frigate_faces = Path("/home/justin/frigate/media/clips/faces")
            people = store.get_known_people()
            deployed = []
            for person in people:
                name = person["person_name"]
                embeddings = store.get_embeddings_for_person(name)
                # Take top 10 highest-confidence verified embeddings
                top = sorted(
                    [e for e in embeddings if e.get("verified") and e.get("image_path")],
                    key=lambda x: x.get("confidence", 0),
                    reverse=True,
                )[:10]
                dest_dir = frigate_faces / name
                dest_dir.mkdir(parents=True, exist_ok=True)
                for i, entry in enumerate(top):
                    src = Path(entry["image_path"])
                    if src.exists():
                        shutil.copy2(src, dest_dir / f"{i:03d}.jpg")
                deployed.append({"person": name, "images": len(top)})
            return {"deployed": deployed}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error deploying to Frigate")
            raise HTTPException(status_code=500, detail="Internal server error") from None
```

**Step 4: Register in `aria/hub/api.py`**

Find the line in `api.py` that calls the last `_register_*_routes` function (before `return router`) and add:

```python
# In create_api() or the route registration block, after existing registrations:
from aria.hub.routes_faces import _register_face_routes
_register_face_routes(router, hub)
```

Also add `hub.faces_store` initialization. Find where `IntelligenceHub.__init__` initializes other stores (near `events_db_path`) and add:

```python
# In aria/hub/core.py, near line 104 (alongside events.db):
from aria.faces.store import FaceEmbeddingStore as _FaceStore
faces_db_path = str(Path(cache_path).parent / "faces.db")
self.faces_store = _FaceStore(faces_db_path)
self.faces_store.initialize()
```

**Step 5: Run tests**

```bash
python3 -m pytest tests/hub/test_api_faces.py -v --timeout=30
```

**Step 6: Run full test suite — check nothing broken**

```bash
python3 -m pytest tests/ -x -q --timeout=120 2>&1 | tail -10
```

**Step 7: Commit**

```bash
git add aria/hub/routes_faces.py aria/hub/core.py aria/hub/api.py tests/hub/test_api_faces.py
git commit -m "feat: add /api/faces/* routes — queue, label, people, stats, bootstrap, deploy"
```

---

## Task 7: Extend presence.py — hook live pipeline

**Files:**
- Modify: `aria/modules/presence.py` (lines ~481–540)
- Modify: `tests/hub/test_presence.py`

**Step 1: Find the hook point**

```bash
grep -n "_handle_frigate_event\|sub_label" aria/modules/presence.py | head -20
```

**Step 2: Add pipeline call in `_handle_frigate_event`**

After reading the existing face handling code (around line 522), add:

```python
# After existing sub_label handling, add:
if event_type == "end" and label == "person":
    snapshot_url = f"{self._frigate_url}/api/events/{event_id}/snapshot.jpg"
    asyncio.create_task(self._process_face_async(event_id, snapshot_url))
```

Add the async method to the presence module class:

```python
async def _process_face_async(self, event_id: str, snapshot_url: str) -> None:
    """Extract face from Frigate snapshot and run live pipeline."""
    import tempfile, aiohttp
    from aria.faces.pipeline import FacePipeline

    if not hasattr(self.hub, "faces_store"):
        return

    pipeline = FacePipeline(store=self.hub.faces_store, frigate_url=self._frigate_url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(snapshot_url) as resp:
                if resp.status != 200:
                    return
                img_data = await resp.read()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(img_data)
            tmp_path = f.name

        embedding = pipeline.extractor.extract_embedding(tmp_path)
        if embedding is None:
            return

        result = pipeline.process_embedding(embedding, event_id, image_path=tmp_path)

        if result["action"] == "auto_label":
            person_name = result["person_name"]
            confidence = result["confidence"]
            # Update identified persons — existing ARIA presence tracking
            self._identified_persons[person_name] = {
                "room": self._resolve_camera_room(event_id),
                "last_seen": asyncio.get_event_loop().time(),
                "confidence": confidence,
                "source": "face_recognition",
            }
            self._logger.debug("Face auto-labeled: %s (%.2f)", person_name, confidence)

    except Exception:
        self._logger.exception("Face pipeline error for event %s", event_id)
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
```

**Step 3: Run presence tests — ensure nothing broken**

```bash
python3 -m pytest tests/hub/test_presence.py -v --timeout=60 2>&1 | tail -15
```

**Step 4: Commit**

```bash
git add aria/modules/presence.py
git commit -m "feat: hook face pipeline into presence module — auto-label live Frigate events"
```

---

## Task 8: Bootstrap UI — Faces.jsx

**Files:**
- Create: `aria/dashboard/spa/src/pages/Faces.jsx`
- Modify: `aria/dashboard/spa/src/components/Sidebar.jsx`
- Modify: `aria/dashboard/spa/src/app.jsx`

**Step 1: Create Faces.jsx**

`aria/dashboard/spa/src/pages/Faces.jsx`:
```jsx
import { useState, useEffect } from 'preact/hooks';

export default function Faces() {
  const [stats, setStats] = useState({ queue_depth: 0, known_people: 0 });
  const [queue, setQueue] = useState([]);
  const [people, setPeople] = useState([]);
  const [labelInput, setLabelInput] = useState({});
  const [bootstrapRunning, setBootstrapRunning] = useState(false);
  const [error, setError] = useState(null);

  async function fetchData() {
    try {
      const [statsRes, queueRes, peopleRes] = await Promise.all([
        fetch('/api/faces/stats'),
        fetch('/api/faces/queue?limit=20'),
        fetch('/api/faces/people'),
      ]);
      setStats(await statsRes.json());
      const queueData = await queueRes.json();
      setQueue(queueData.items || []);
      const peopleData = await peopleRes.json();
      setPeople(peopleData.people || []);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { fetchData(); }, []);

  async function handleLabel(queueId) {
    const name = labelInput[queueId]?.trim();
    if (!name) return;
    await fetch('/api/faces/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queue_id: queueId, person_name: name }),
    });
    setLabelInput(prev => ({ ...prev, [queueId]: '' }));
    fetchData();
  }

  async function handleBootstrap() {
    setBootstrapRunning(true);
    await fetch('/api/faces/bootstrap', { method: 'POST' });
    setTimeout(() => { setBootstrapRunning(false); fetchData(); }, 3000);
  }

  async function handleDeploy() {
    await fetch('/api/faces/deploy', { method: 'POST' });
    alert('Deployed to Frigate — restart Frigate to reload face library.');
  }

  return (
    <div class="p-4 max-w-4xl mx-auto">
      <h1 class="text-2xl font-bold mb-4">Face Recognition</h1>

      {error && <div class="text-red-500 mb-4">{error}</div>}

      {/* Stats */}
      <div class="grid grid-cols-2 gap-4 mb-6">
        <div class="bg-gray-800 rounded p-4 text-center">
          <div class="text-3xl font-bold text-yellow-400">{stats.queue_depth}</div>
          <div class="text-sm text-gray-400">Pending review</div>
        </div>
        <div class="bg-gray-800 rounded p-4 text-center">
          <div class="text-3xl font-bold text-green-400">{stats.known_people}</div>
          <div class="text-sm text-gray-400">Known people</div>
        </div>
      </div>

      {/* Bootstrap */}
      <div class="bg-gray-800 rounded p-4 mb-6">
        <h2 class="text-lg font-semibold mb-2">Bootstrap from Frigate Clips</h2>
        <p class="text-sm text-gray-400 mb-3">
          Run once to extract and cluster faces from all existing snapshots.
          Then label each cluster below.
        </p>
        <div class="flex gap-2">
          <button
            onClick={handleBootstrap}
            disabled={bootstrapRunning}
            class="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded text-sm"
          >
            {bootstrapRunning ? 'Running...' : 'Run Bootstrap'}
          </button>
          <button
            onClick={handleDeploy}
            class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded text-sm"
          >
            Deploy to Frigate
          </button>
        </div>
      </div>

      {/* Review Queue */}
      {queue.length > 0 && (
        <div class="mb-6">
          <h2 class="text-lg font-semibold mb-3">Review Queue ({stats.queue_depth})</h2>
          <div class="space-y-3">
            {queue.map(item => (
              <div key={item.id} class="bg-gray-800 rounded p-3 flex gap-3 items-start">
                <img
                  src={`/api/events/${item.event_id}/snapshot.jpg`}
                  class="w-20 h-20 object-cover rounded"
                  onError={e => { e.target.style.display = 'none'; }}
                />
                <div class="flex-1">
                  <div class="text-xs text-gray-400 mb-1">Priority: {item.priority?.toFixed(2)}</div>
                  {item.top_candidates?.map(c => (
                    <div key={c.name} class="text-sm text-gray-300">
                      {c.name}: {(c.confidence * 100).toFixed(0)}%
                    </div>
                  ))}
                  <div class="flex gap-2 mt-2">
                    <input
                      type="text"
                      placeholder="Name or skip"
                      value={labelInput[item.id] || ''}
                      onInput={e => setLabelInput(prev => ({ ...prev, [item.id]: e.target.value }))}
                      class="bg-gray-700 px-2 py-1 rounded text-sm flex-1"
                    />
                    <button
                      onClick={() => handleLabel(item.id)}
                      class="bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded text-sm"
                    >
                      Label
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* People Roster */}
      {people.length > 0 && (
        <div>
          <h2 class="text-lg font-semibold mb-3">Known People</h2>
          <div class="grid grid-cols-2 gap-2">
            {people.map(person => (
              <div key={person.person_name} class="bg-gray-800 rounded p-3 flex justify-between">
                <span class="font-medium">{person.person_name}</span>
                <span class="text-gray-400 text-sm">{person.count} samples</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Add to Sidebar.jsx — System section**

In `aria/dashboard/spa/src/components/Sidebar.jsx`, find `NAV_ITEMS` and add after the Validation entry:

```jsx
{ path: '/faces', label: 'Faces', icon: UserIcon, system: true },
```

Add the `UserIcon` SVG near the other icons:

```jsx
function UserIcon() {
  return (
    <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
      <circle cx="12" cy="7" r="4"/>
    </svg>
  );
}
```

**Step 3: Add route in `app.jsx`**

```jsx
// Add import
import Faces from './pages/Faces.jsx';

// Add route in Router
<Faces path="/faces" />
```

**Step 4: Build and verify**

```bash
cd aria/dashboard/spa
npm run build
cd ../../..

# Restart ARIA
systemctl --user restart aria-hub

# Verify page loads
curl -s http://127.0.0.1:8001/ui/ | grep -c "faces" || true
# Navigate to http://127.0.0.1:8001/ui/#/faces in browser
```

**Step 5: Commit**

```bash
git add aria/dashboard/spa/src/pages/Faces.jsx \
        aria/dashboard/spa/src/components/Sidebar.jsx \
        aria/dashboard/spa/src/app.jsx \
        aria/dashboard/spa/dist/
git commit -m "feat: add Faces page to ARIA UI — bootstrap panel, review queue, people roster"
```

---

## Task 9: Run bootstrap on real data

**This is a manual execution task, not a code task.**

```bash
# 1. Check ARIA is running with new face routes
curl -s http://127.0.0.1:8001/api/faces/stats | python3 -m json.tool

# 2. Trigger bootstrap via API (runs in background, takes 15-30 min)
curl -s -X POST http://127.0.0.1:8001/api/faces/bootstrap | python3 -m json.tool

# 3. Monitor progress in ARIA logs
journalctl --user -u aria-hub -f | grep -i "bootstrap\|face"

# 4. When complete, check cluster results
curl -s http://127.0.0.1:8001/api/faces/stats | python3 -m json.tool
# Expected: queue_depth > 0

# 5. Open ARIA UI to label clusters
# Navigate to: http://127.0.0.1:8001/ui/#/faces
# Label each person in the review queue

# 6. Deploy labeled faces to Frigate
curl -s -X POST http://127.0.0.1:8001/api/faces/deploy | python3 -m json.tool

# 7. Reload Frigate config to pick up new face training data
docker exec frigate kill -HUP 1
# Or: docker restart frigate
```

---

## Task 10: Prune Frigate recordings

**Only execute after bootstrap + labeling + deploy are complete (Task 9 done).**

```bash
# Verify faces are deployed before pruning
ls /home/justin/frigate/media/clips/faces/
# Expected: at least one named directory

# Check current disk usage
df -h / | awk 'NR==2{print "Used: "$3, "Free: "$4}'

# Option A — Update Frigate retention to 7 days (recordings auto-prune)
# Edit /home/justin/frigate/config/config.yml:
# record:
#   retain:
#     days: 7  # already set
# This will prune old recordings on next Frigate restart

# Option B — Manual prune of recordings older than 14 days
find /home/justin/frigate/media/recordings/ \
  -type d -name "2026-02-*" \
  -not -newer /tmp/14days_ago \
  | head -5  # preview first

# Create the reference timestamp
touch -d "14 days ago" /tmp/14days_ago

# Preview what would be deleted (DRY RUN)
find /home/justin/frigate/media/recordings/ \
  -maxdepth 1 -type d \
  ! -newer /tmp/14days_ago \
  | sort

# Execute prune (after previewing)
docker exec frigate python3 -c "
import os, shutil
from pathlib import Path
recordings = Path('/media/frigate/recordings')
import time
cutoff = time.time() - (14 * 86400)
for day_dir in sorted(recordings.iterdir()):
    if day_dir.stat().st_mtime < cutoff:
        print(f'Pruning {day_dir}')
        shutil.rmtree(day_dir)
"

# Verify disk reclaimed
df -h / | awk 'NR==2{print "Used: "$3, "Free: "$4}'

# Download qwen2.5-coder:32b now that disk is free
ollama pull qwen2.5-coder:32b
```

---

## Verification

```bash
# 1. Full test suite
python3 -m pytest tests/ -x -q --timeout=120 2>&1 | tail -10
# Expected: all pass (no regressions)

# 2. API smoke test
curl -s http://127.0.0.1:8001/api/faces/stats | python3 -m json.tool
curl -s http://127.0.0.1:8001/api/faces/queue | python3 -m json.tool
curl -s http://127.0.0.1:8001/api/faces/people | python3 -m json.tool

# 3. Presence check — after bootstrap + labeling
curl -s http://127.0.0.1:8001/api/cache/presence | python3 -m json.tool | grep -A5 "identified"

# 4. ARIA UI
# Open http://127.0.0.1:8001/ui/#/faces — Faces page should load
# Queue should show pending items (after bootstrap)
# People roster should show labeled people (after labeling)
```

---

## AAR Checklist (after completion)

- [ ] Were any Cluster B (integration boundary) bugs found? (ARIA→Frigate writeback, face pipeline→presence module)
- [ ] Did bootstrap cluster purity meet the 60% pivot trigger? If not, switch to recording frame extraction
- [ ] Any silent failures in face pipeline? (`_process_face_async` must log exceptions — never swallow)
- [ ] Create `docs/plans/YYYY-MM-DD-aar-face-recognition.md` using `docs/plans/TEMPLATE-AAR.md`
