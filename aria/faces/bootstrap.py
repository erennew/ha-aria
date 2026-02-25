"""Bootstrap pipeline: batch-process Frigate clips → DBSCAN clusters."""

import hashlib
import logging
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN

from aria.faces.extractor import FaceExtractor
from aria.faces.store import FaceEmbeddingStore

logger = logging.getLogger(__name__)

# DBSCAN params tuned for FaceNet512 cosine distance.
# eps=0.4: faces within cosine distance 0.4 group together (~similar person)
# min_samples=2: at least 2 images to form a cluster (filters one-off detections)
DBSCAN_EPS = 0.4
DBSCAN_MIN_SAMPLES = 2


class BootstrapPipeline:
    """One-time batch extraction + DBSCAN clustering of Frigate clip snapshots."""

    def __init__(self, clips_dir: str, store: FaceEmbeddingStore):
        self.clips_dir = clips_dir
        self.store = store
        self.extractor = FaceExtractor()

    def scan_clips(self) -> list[str]:
        """Return all .jpg snapshot paths in clips_dir, sorted."""
        return sorted(str(p) for p in Path(self.clips_dir).glob("*.jpg"))

    def extract_all(self, image_paths: list[str], progress=None) -> tuple[list[str], list[np.ndarray]]:
        """Extract embeddings from all images, skipping failures.

        Args:
            image_paths: Image file paths to process.
            progress: Optional progress tracker with an ``update(processed)`` method.

        Returns:
            (valid_paths, embeddings) — only images where a face was detected
        """
        valid_paths: list[str] = []
        embeddings: list[np.ndarray] = []
        total = len(image_paths)
        for i, path in enumerate(image_paths):
            if i % 100 == 0:
                logger.info("Bootstrap: %d/%d images processed", i, total)
            if i % 10 == 0 and progress is not None:
                progress.update(i)
            embedding = self.extractor.extract_embedding(path)
            if embedding is not None:
                valid_paths.append(path)
                embeddings.append(embedding)
        if progress is not None:
            progress.update(total)
        logger.info(
            "Bootstrap: %d/%d images had detectable faces",
            len(valid_paths),
            total,
        )
        return valid_paths, embeddings

    def cluster_embeddings(self, embeddings: list[np.ndarray]) -> list[int]:
        """DBSCAN cluster embeddings by cosine distance.

        Returns list of integer cluster labels (-1 = noise/unknown).
        """
        matrix = np.stack(embeddings)
        db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES, metric="cosine")
        return db.fit_predict(matrix).tolist()

    def build_clusters(self, paths: list[str], labels: list[int]) -> dict[str, list[str]]:
        """Group image paths by cluster label.

        Returns:
            {"cluster_0": [...], "cluster_1": [...], "unknown": [...]}
            'unknown' contains DBSCAN noise points (label -1)
        """
        clusters: dict[str, list[str]] = {}
        for path, label in zip(paths, labels, strict=False):
            key = "unknown" if label == -1 else f"cluster_{label}"
            clusters.setdefault(key, []).append(path)
        return clusters

    def run(self, progress=None) -> dict[str, list[str]]:
        """Execute full bootstrap: scan → extract → cluster.

        Args:
            progress: Optional progress tracker with ``start(total)`` and
                ``update(processed)`` methods called from this thread.

        Saves all embeddings to store with person_name=None (unidentified).
        Returns cluster dict for UI review.
        """
        logger.info("Bootstrap: scanning %s", self.clips_dir)
        image_paths = self.scan_clips()
        total = len(image_paths)
        logger.info("Bootstrap: found %d snapshots", total)
        if progress is not None:
            progress.start(total)

        valid_paths, embeddings = self.extract_all(image_paths, progress)
        if not embeddings:
            logger.warning("Bootstrap: no faces detected in any snapshots")
            return {}

        labels = self.cluster_embeddings(embeddings)

        # Persist all embeddings as unidentified (person_name=None).
        # Use a short hash of the image path as event_id so re-runs are
        # idempotent — the partial unique index only covers source='live',
        # so without a stable per-image key, re-running doubles the rows.
        for path, embedding, _label in zip(valid_paths, embeddings, labels, strict=False):
            path_id = "bs_" + hashlib.sha1(path.encode()).hexdigest()[:12]
            try:
                self.store.add_embedding(
                    person_name=None,
                    embedding=embedding,
                    event_id=path_id,
                    image_path=path,
                    confidence=0.0,
                    source="bootstrap",
                    verified=False,
                )
            except Exception:
                # Duplicate on re-run — skip silently (image already stored)
                logger.debug("Bootstrap: skipping duplicate %s", path_id)

        clusters = self.build_clusters(valid_paths, labels)
        logger.info(
            "Bootstrap complete: %d clusters, %d unknown",
            len([k for k in clusters if k != "unknown"]),
            len(clusters.get("unknown", [])),
        )
        return clusters
