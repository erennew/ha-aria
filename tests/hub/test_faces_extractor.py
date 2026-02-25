"""Tests for FaceExtractor — DeepFace wrapper."""

from unittest.mock import MagicMock, patch

import numpy as np

from aria.faces.extractor import FaceExtractor


def _mock_deepface(represent_return=None, represent_side_effect=None):
    """Return a MagicMock that stands in for the DeepFace class."""
    mock = MagicMock()
    if represent_side_effect is not None:
        mock.represent.side_effect = represent_side_effect
    else:
        mock.represent.return_value = represent_return
    return mock


class TestFaceExtractorEmbedding:
    def test_returns_numpy_array(self):
        """extract_embedding returns 512-d float32 array."""
        extractor = FaceExtractor()
        fake_result = [{"embedding": list(np.random.rand(512))}]
        with patch("aria.faces.extractor._get_deepface", return_value=_mock_deepface(represent_return=fake_result)):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is not None
        assert result.shape == (512,)
        assert result.dtype == np.float32

    def test_returns_none_on_no_face(self):
        """Returns None when DeepFace finds no face."""
        extractor = FaceExtractor()
        with patch(
            "aria.faces.extractor._get_deepface",
            return_value=_mock_deepface(represent_side_effect=ValueError("No face")),
        ):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is None

    def test_returns_none_on_exception(self):
        """Returns None (not raise) on unexpected errors — silent failure prevention."""
        extractor = FaceExtractor()
        with patch(
            "aria.faces.extractor._get_deepface",
            return_value=_mock_deepface(represent_side_effect=Exception("GPU OOM")),
        ):
            result = extractor.extract_embedding("/tmp/fake.jpg")
        assert result is None

    def test_cosine_similarity(self):
        """cosine_similarity returns 1.0 for identical vectors."""
        extractor = FaceExtractor()
        v = np.random.rand(512).astype(np.float32)
        v /= np.linalg.norm(v)
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
            {"person_name": "carter", "embedding": -query.copy()},  # opposite
        ]
        candidates = extractor.find_best_match(query, named, min_threshold=-1.0)
        assert candidates[0]["person_name"] == "justin"
        assert candidates[0]["confidence"] > 0.99
        assert candidates[1]["confidence"] < candidates[0]["confidence"]
