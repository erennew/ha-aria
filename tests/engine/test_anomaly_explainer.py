"""Tests for IsolationForest anomaly explanation engine."""

import numpy as np
from sklearn.ensemble import IsolationForest

from aria.engine.anomaly_explainer import AnomalyExplainer


class TestAnomalyExplainer:
    """Test anomaly explanation via IsolationForest path tracing."""

    def setup_method(self):
        """Create a trained IsolationForest with known structure."""
        np.random.seed(42)
        # Normal data: low values in all 5 features
        normal = np.random.normal(loc=0, scale=1, size=(100, 5))
        self.feature_names = ["power", "lights", "motion", "temp", "humidity"]
        self.model = IsolationForest(n_estimators=50, contamination=0.05, random_state=42)
        self.model.fit(normal)
        self.explainer = AnomalyExplainer()

    def test_explain_returns_top_n(self):
        """Explain returns exactly top_n features."""
        # Anomalous: extreme power value
        anomalous = np.array([[10.0, 0.0, 0.0, 0.0, 0.0]])
        result = self.explainer.explain(self.model, anomalous, self.feature_names, top_n=3)
        assert len(result) == 3
        assert all("feature" in r and "contribution" in r for r in result)

    def test_contributions_sum_to_one_or_less(self):
        """Contributions of top_n features sum to <= 1.0."""
        anomalous = np.array([[10.0, 0.0, 0.0, 0.0, 0.0]])
        result = self.explainer.explain(self.model, anomalous, self.feature_names, top_n=5)
        total = sum(r["contribution"] for r in result)
        assert 0.0 < total <= 1.001  # Allow float rounding

    def test_extreme_feature_ranks_first(self):
        """The feature with the extreme value should rank highest."""
        # Only feature 0 (power) is extreme
        anomalous = np.array([[20.0, 0.1, -0.1, 0.2, -0.2]])
        result = self.explainer.explain(self.model, anomalous, self.feature_names, top_n=3)
        # Power should be the top contributor
        assert result[0]["feature"] == "power"

    def test_explain_with_no_feature_names(self):
        """Falls back to index-based names when feature_names is empty."""
        anomalous = np.array([[10.0, 0.0, 0.0, 0.0, 0.0]])
        result = self.explainer.explain(self.model, anomalous, [], top_n=3)
        assert len(result) == 3
        assert result[0]["feature"].startswith("feature_")

    def test_explain_normal_sample(self):
        """Normal samples still get explanations (lower contributions)."""
        normal = np.array([[0.0, 0.0, 0.0, 0.0, 0.0]])
        result = self.explainer.explain(self.model, normal, self.feature_names, top_n=3)
        assert len(result) == 3

    def test_top_n_capped_at_feature_count(self):
        """top_n larger than feature count returns all features."""
        anomalous = np.array([[10.0, 0.0, 0.0, 0.0, 0.0]])
        result = self.explainer.explain(self.model, anomalous, self.feature_names, top_n=10)
        assert len(result) <= 5  # Only 5 features exist
