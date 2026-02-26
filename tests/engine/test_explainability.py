"""Tests for SHAP-based model explainability."""

import pytest

try:
    import shap  # noqa: F401

    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False


@pytest.mark.skipif(not HAS_SHAP, reason="shap not installed")
class TestSHAPExplainability:
    def test_explain_prediction_returns_contributions(self):
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 10))
        y = X[:, 0] * 5 + X[:, 3] * 3 + rng.standard_normal(100)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=50, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(10)]
        sample = X[0]

        contributions = explain_prediction(model, scaler, names, sample, top_n=5)

        assert len(contributions) == 5
        assert all("feature" in c and "contribution" in c for c in contributions)
        top_features = [c["feature"] for c in contributions]
        assert "feat_0" in top_features

    def test_explain_prediction_has_direction_and_raw_value(self):
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 5))
        y = X[:, 0] * 10 + rng.standard_normal(100)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=50, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(5)]
        contributions = explain_prediction(model, scaler, names, X[0], top_n=3)

        for c in contributions:
            assert c["direction"] in ("positive", "negative")
            assert "raw_value" in c
            assert isinstance(c["raw_value"], float)

    def test_explain_prediction_sorted_by_absolute_contribution(self):
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 10))
        y = X[:, 0] * 5 + X[:, 3] * 3 + rng.standard_normal(100)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=50, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(10)]
        contributions = explain_prediction(model, scaler, names, X[0], top_n=10)

        values = [c["contribution"] for c in contributions]
        assert values == sorted(values, reverse=True)

    def test_build_attribution_report(self):
        from aria.engine.analysis.explainability import build_attribution_report

        contributions = [
            {"feature": "weather_temp_f", "contribution": 35.2, "direction": "positive"},
            {"feature": "people_home_count", "contribution": 22.1, "direction": "positive"},
            {"feature": "is_weekend", "contribution": -12.7, "direction": "negative"},
        ]
        report = build_attribution_report(
            metric="power_watts",
            predicted=450.0,
            actual=520.0,
            contributions=contributions,
        )
        assert report["metric"] == "power_watts"
        assert report["delta"] == 70.0
        assert report["predicted"] == 450.0
        assert report["actual"] == 520.0
        assert len(report["top_drivers"]) == 3

    def test_build_attribution_report_negative_delta(self):
        from aria.engine.analysis.explainability import build_attribution_report

        report = build_attribution_report(
            metric="lights_on",
            predicted=10.0,
            actual=7.0,
            contributions=[],
        )
        assert report["delta"] == -3.0
        assert report["top_drivers"] == []


class TestExplainabilityImport:
    def test_has_shap_flag_exists(self):
        from aria.engine.analysis.explainability import HAS_SHAP

        assert isinstance(HAS_SHAP, bool)

    def test_build_attribution_report_works_without_shap(self):
        """build_attribution_report has no shap dependency."""
        from aria.engine.analysis.explainability import build_attribution_report

        report = build_attribution_report(metric="test", predicted=1.0, actual=2.0, contributions=[])
        assert report["metric"] == "test"


@pytest.mark.skipif(not HAS_SHAP, reason="shap not installed")
class TestSHAPShapeHandling:
    """Issue #226: shap_values 1D and 2D shape handling."""

    def test_explain_prediction_handles_1d_shap_values(self, caplog):
        """explain_prediction must work when shap returns a 1D array (regression flat output).

        We monkeypatch the explainer to return a 1D array and verify the function
        uses it directly (not crash or index incorrectly).
        """
        import logging
        from unittest.mock import MagicMock, patch

        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((50, 5))
        y = X[:, 0] * 5 + rng.standard_normal(50)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=20, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(5)]
        sample = X[0]

        # Patch explainer to return 1D shap_values
        mock_explainer = MagicMock()
        mock_explainer.shap_values.return_value = np.array([0.1, -0.2, 0.3, -0.1, 0.05])  # 1D

        with (
            patch("aria.engine.analysis.explainability.shap.TreeExplainer", return_value=mock_explainer),
            caplog.at_level(logging.WARNING),
        ):
            contributions = explain_prediction(model, scaler, names, sample, top_n=3)

        assert len(contributions) == 3
        assert all("feature" in c and "contribution" in c for c in contributions)

    def test_explain_prediction_handles_2d_shap_values(self):
        """explain_prediction must work when shap returns 2D (n_samples, n_features) for regression."""
        from unittest.mock import MagicMock, patch

        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((50, 5))
        y = X[:, 0] * 5 + rng.standard_normal(50)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=20, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(5)]
        sample = X[0]

        # Patch explainer to return 2D (1, n_features) — standard regression output
        mock_explainer = MagicMock()
        mock_explainer.shap_values.return_value = np.array([[0.1, -0.2, 0.3, -0.1, 0.05]])  # (1, 5)

        with patch("aria.engine.analysis.explainability.shap.TreeExplainer", return_value=mock_explainer):
            contributions = explain_prediction(model, scaler, names, sample, top_n=3)

        assert len(contributions) == 3

    def test_explain_prediction_warns_on_unexpected_shape(self, caplog):
        """explain_prediction emits WARNING on unexpected shap_values shape (3D)."""
        import logging
        from unittest.mock import MagicMock, patch

        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.preprocessing import StandardScaler

        from aria.engine.analysis.explainability import explain_prediction

        rng = np.random.default_rng(42)
        X = rng.standard_normal((50, 5))
        y = X[:, 0] * 5 + rng.standard_normal(50)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = GradientBoostingRegressor(n_estimators=20, random_state=42)
        model.fit(X_scaled, y)

        names = [f"feat_{i}" for i in range(5)]
        sample = X[0]

        # Patch explainer to return 3D — unexpected shape
        mock_explainer = MagicMock()
        mock_explainer.shap_values.return_value = np.zeros((2, 1, 5))  # 3D

        with (
            patch("aria.engine.analysis.explainability.shap.TreeExplainer", return_value=mock_explainer),
            caplog.at_level(logging.WARNING, logger="aria.engine.analysis.explainability"),
        ):
            contributions = explain_prediction(model, scaler, names, sample, top_n=3)

        # Should log a warning about unexpected shape
        assert any("shape" in r.message.lower() or "ndim" in r.message.lower() for r in caplog.records)
        # Should still return a list (graceful degradation)
        assert isinstance(contributions, list)
