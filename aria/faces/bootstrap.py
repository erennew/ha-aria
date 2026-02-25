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

    def scan_clips(self, max_bytes: int | None = None) -> list[str]:
        """Return .jpg snapshot paths in clips_dir, sorted by mtime (newest last).

        If max_bytes is set, the oldest files that push total size over the limit
        are deleted before processing begins. This prevents unbounded growth in
        the Frigate clips directory.
        """
        stats = sorted(
            ((p, p.stat()) for p in Path(self.clips_dir).glob("*.jpg")),
            key=lambda t: t[1].st_mtime,
        )
        if max_bytes is not None:
            total = sum(s.st_size for _, s in stats)
            for p, st in stats[:]:
                if total <= max_bytes:
                    break
                try:
                    p.unlink()
                    total -= st.st_size
                    stats.remove((p, st))
                    logger.debug("Evicted old clip: %s", p.name)
                except OSError:
                    logger.warning("Failed to evict clip %s", p)
        return [str(p) for p, _ in stats]

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
        import os

        _GB = 1024**3
        max_gb_env = os.environ.get("ARIA_FACES_CLIPS_MAX_GB")
        max_bytes = int(float(max_gb_env) * _GB) if max_gb_env else None
        cap_label = f"{max_gb_env} GB" if max_gb_env else "unlimited"
        logger.info("Bootstrap: scanning %s (clips_cap=%s)", self.clips_dir, cap_label)
        image_paths = self.scan_clips(max_bytes=max_bytes)
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
        for path, embedding, label in zip(valid_paths, embeddings, labels, strict=False):
            path_id = "bs_" + hashlib.sha1(path.encode()).hexdigest()[:12]
            is_new = False
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
                is_new = True
            except Exception:
                # Duplicate on re-run — skip silently (image already stored)
                logger.debug("Bootstrap: skipping duplicate %s", path_id)

            # Add new faces to review queue so the UI can display them for labeling.
            # Cluster label becomes top candidate hint (unknown = -1).
            if is_new:
                cluster_hint = f"cluster_{label}" if label != -1 else "unknown"
                try:
                    self.store.add_to_review_queue(
                        event_id=path_id,
                        image_path=path,
                        embedding=embedding,
                        top_candidates=[{"person_name": cluster_hint, "confidence": 0.0}],
                        priority=0.5,
                    )
                except Exception:
                    logger.warning("Bootstrap: queue insert failed for %s", path_id, exc_info=True)

        clusters = self.build_clusters(valid_paths, labels)
        logger.info(
            "Bootstrap complete: %d clusters, %d unknown",
            len([k for k in clusters if k != "unknown"]),
            len(clusters.get("unknown", [])),
        )
        return clusters
