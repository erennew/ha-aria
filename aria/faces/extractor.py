"""DeepFace wrapper for face detection and embedding extraction."""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Module-level sentinel — populated on first successful import inside extract_embedding.
# True lazy: DeepFace is never imported at module load so ARIA startup stays fast
# and tf-keras/retinaface dependency errors don't break the test suite.
_DeepFace = None
_deepface_import_attempted = False


def _get_deepface():
    """Return DeepFace class, importing on first call. Returns None if unavailable."""
    global _DeepFace, _deepface_import_attempted
    if _deepface_import_attempted:
        return _DeepFace
    _deepface_import_attempted = True
    try:
        from deepface import DeepFace  # noqa: PLC0415

        _DeepFace = DeepFace
    except (ImportError, Exception):
        logger.error("FaceExtractor: deepface not available — face recognition disabled")
        _DeepFace = None
    return _DeepFace


class FaceExtractor:
    """Extract 512-d FaceNet512 embeddings from image files."""

    MODEL = "Facenet512"
    DETECTOR = "retinaface"  # Best for surveillance footage angles

    def extract_embedding(self, image_path: str) -> np.ndarray | None:
        """Return 512-d float32 L2-normalized embedding, or None if no face detected."""
        DeepFace = _get_deepface()
        if DeepFace is None:
            logger.error("FaceExtractor: deepface not installed")
            return None
        try:
            result = DeepFace.represent(
                img_path=image_path,
                model_name=self.MODEL,
                detector_backend=self.DETECTOR,
                enforce_detection=True,
            )
            if not result:
                return None
            vec = np.array(result[0]["embedding"], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm == 0:
                return None
            return vec / norm  # L2 normalize for cosine similarity
        except ValueError:
            # No face detected — expected for many surveillance snapshots
            return None
        except Exception:
            logger.exception("FaceExtractor: unexpected error on %s", image_path)
            return None

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalized vectors.

        Both inputs must be L2-normalized (unit vectors). For normalized vectors,
        cosine similarity reduces to the dot product — O(n) with no sqrt.
        """
        return float(np.dot(a, b))

    def find_best_match(
        self,
        query: np.ndarray,
        named_embeddings: list[dict],
        min_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Compare query against named embeddings, return sorted candidates.

        Groups multiple embeddings per person and averages similarity scores,
        which is more robust to outlier embeddings than taking the maximum.

        Args:
            query: 512-d L2-normalized embedding to match
            named_embeddings: list of {person_name, embedding} dicts
            min_threshold: discard candidates below this confidence

        Returns:
            List of {person_name, confidence} sorted by confidence descending
        """
        scores: dict[str, list[float]] = {}
        for entry in named_embeddings:
            name = entry["person_name"]
            sim = self.cosine_similarity(query, entry["embedding"])
            scores.setdefault(name, []).append(sim)

        candidates = [
            {"person_name": name, "confidence": float(np.mean(sims))}
            for name, sims in scores.items()
            if float(np.mean(sims)) >= min_threshold
        ]
        return sorted(candidates, key=lambda x: x["confidence"], reverse=True)
