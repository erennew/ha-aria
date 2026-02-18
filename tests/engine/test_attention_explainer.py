"""Tests for attention-based anomaly explainer (Tier 4).

Tests are written to work both with and without torch installed.
When torch is unavailable, tests verify graceful fallback behavior.
"""

# Check if torch is available for conditional test running
import importlib.util

import numpy as np
import pytest

from aria.engine.attention_explainer import AttentionExplainer

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


class TestAttentionExplainerInit:
    """Test initialization and torch detection."""

    def test_creates_without_torch(self):
        """Should initialize even without torch."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6)
        assert explainer.n_features == 5
        assert explainer.sequence_length == 6

    def test_torch_availability_detected(self):
        """Should report whether torch is available."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6)
        assert isinstance(explainer.torch_available, bool)

    def test_is_trained_false_initially(self):
        explainer = AttentionExplainer(n_features=5, sequence_length=6)
        assert not explainer.is_trained


class TestFallbackBehavior:
    """Test behavior when torch is not available or model not trained."""

    def test_explain_untrained_returns_empty(self):
        """Untrained explainer returns empty explanations."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6)
        window = np.zeros((6, 5))
        result = explainer.explain(window)
        assert result["feature_contributions"] == []
        assert result["temporal_attention"] == []
        assert result["contrastive_explanation"] is None
        assert result["anomaly_score"] is None

    def test_get_stats_untrained(self):
        """Stats report untrained state."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6)
        stats = explainer.get_stats()
        assert stats["is_trained"] is False
        assert stats["n_features"] == 5
        assert stats["sequence_length"] == 6


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")
class TestWithTorch:
    """Tests that require torch — skipped on Tier 1-3 machines."""

    def test_build_model(self):
        """Model builds with correct parameter count."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6, hidden_dim=32)
        assert explainer._model is not None
        param_count = sum(p.numel() for p in explainer._model.parameters())
        # Should be roughly 10K-100K parameters
        assert 1_000 < param_count < 200_000

    def test_train_on_synthetic_data(self):
        """Train on synthetic normal data."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6, hidden_dim=16)
        np.random.seed(42)
        # 50 normal windows
        X_train = np.random.normal(0, 1, (50, 6, 5))
        result = explainer.train(X_train, epochs=5)
        assert result["trained"] is True
        assert result["final_loss"] > 0
        assert explainer.is_trained

    def test_explain_after_training(self):
        """Explain an anomalous window after training."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6, hidden_dim=16)
        np.random.seed(42)
        X_train = np.random.normal(0, 1, (50, 6, 5))
        explainer.train(X_train, epochs=5)

        # Anomalous window: spike in feature 0
        anomaly_window = np.zeros((6, 5))
        anomaly_window[:, 0] = 10.0

        result = explainer.explain(anomaly_window)
        assert len(result["feature_contributions"]) > 0
        assert len(result["temporal_attention"]) == 6
        assert result["anomaly_score"] is not None
        # Temporal attention should sum to ~1
        attn_sum = sum(result["temporal_attention"])
        assert 0.5 < attn_sum < 1.5

    def test_contrastive_explanation(self):
        """Contrastive explanation compares anomaly to normal baseline."""
        explainer = AttentionExplainer(n_features=5, sequence_length=6, hidden_dim=16)
        np.random.seed(42)
        X_train = np.random.normal(0, 1, (50, 6, 5))
        explainer.train(X_train, epochs=5)

        anomaly_window = np.zeros((6, 5))
        anomaly_window[:, 0] = 10.0

        result = explainer.explain(
            anomaly_window,
            feature_names=["power", "lights", "motion", "temp", "humidity"],
        )
        assert result["contrastive_explanation"] is not None
        assert isinstance(result["contrastive_explanation"], str)
        assert len(result["contrastive_explanation"]) > 0
