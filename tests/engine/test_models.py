"""Tests for ML models: training, anomaly detection, device failure, blending."""

import importlib.util
import os
import pathlib
import shutil
import tempfile
import unittest

import pytest

from aria.engine.collectors.snapshot import build_empty_snapshot
from aria.engine.config import HolidayConfig, PathConfig
from aria.engine.features.feature_config import DEFAULT_FEATURE_CONFIG
from aria.engine.features.vector_builder import build_training_data
from aria.engine.models.device_failure import (
    detect_contextual_anomalies,
    predict_device_failures,
    train_device_failure_model,
)
from aria.engine.models.isolation_forest import IsolationForestModel
from aria.engine.models.training import (
    _persist_anomaly_status,
    blend_predictions,
    count_days_of_data,
    predict_with_ml,
    train_continuous_model,
)

_spec = importlib.util.spec_from_file_location(
    "engine_conftest",
    pathlib.Path(__file__).parent / "conftest.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
make_synthetic_snapshots = _mod.make_synthetic_snapshots


HAS_SKLEARN = True
try:
    import numpy  # noqa: F401
except ImportError:
    HAS_SKLEARN = False


class TestSklearnTraining(unittest.TestCase):
    def test_train_continuous_model_synthetic(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = make_synthetic_snapshots(120)
            config = DEFAULT_FEATURE_CONFIG
            names, X, targets = build_training_data(snapshots, config)
            result = train_continuous_model("power_watts", names, X, targets["power_watts"], tmpdir)
            self.assertNotIn("error", result)
            self.assertIn("r2", result)
            self.assertIn("mae", result)
            self.assertGreater(result["samples_train"], 0)
            self.assertGreater(result["samples_val"], 0)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "power_watts.pkl")))
            self.assertIn("feature_importance", result)
        finally:
            shutil.rmtree(tmpdir)

    def test_train_continuous_model_insufficient_data(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        result = train_continuous_model("test", ["a", "b"], [[1, 2]] * 10, [1] * 10, "/tmp")
        self.assertIn("error", result)
        self.assertIn("insufficient", result["error"])

    def test_train_anomaly_detector(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = make_synthetic_snapshots(120)
            config = DEFAULT_FEATURE_CONFIG
            names, X, _ = build_training_data(snapshots, config)
            iso_model = IsolationForestModel()
            result = iso_model.train(names, X, tmpdir)
            self.assertNotIn("error", result)
            self.assertEqual(result["samples"], 120)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "anomaly_detector.pkl")))
        finally:
            shutil.rmtree(tmpdir)

    def test_detect_contextual_anomalies(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = make_synthetic_snapshots(120)
            config = DEFAULT_FEATURE_CONFIG
            names, X, _ = build_training_data(snapshots, config)
            iso_model = IsolationForestModel()
            iso_model.train(names, X, tmpdir)
            result = detect_contextual_anomalies(X[25], tmpdir)
            self.assertIn("is_anomaly", result)
            self.assertIn("anomaly_score", result)
        finally:
            shutil.rmtree(tmpdir)

    def test_train_device_failure_model(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = []
            for i in range(30):
                snap = build_empty_snapshot(f"2026-02-{(i % 28) + 1:02d}", HolidayConfig())
                snap["batteries"] = {"sensor.flaky": {"level": 30}}
                if i % 5 == 0:
                    snap["entities"]["unavailable_list"] = ["sensor.flaky"]
                else:
                    snap["entities"]["unavailable_list"] = []
                snapshots.append(snap)
            result = train_device_failure_model(snapshots, tmpdir)
            self.assertNotIn("error", result)
            self.assertGreater(result["samples"], 0)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "device_failure.pkl")))
        finally:
            shutil.rmtree(tmpdir)

    def test_predict_device_failures(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = []
            for i in range(30):
                snap = build_empty_snapshot(f"2026-02-{(i % 28) + 1:02d}", HolidayConfig())
                snap["batteries"] = {"sensor.flaky": {"level": 10}}
                if i % 3 == 0:
                    snap["entities"]["unavailable_list"] = ["sensor.flaky"]
                else:
                    snap["entities"]["unavailable_list"] = []
                snapshots.append(snap)
            train_device_failure_model(snapshots, tmpdir)
            preds = predict_device_failures(snapshots, tmpdir)
            self.assertIsInstance(preds, list)
        finally:
            shutil.rmtree(tmpdir)

    def test_predict_with_ml(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        tmpdir = tempfile.mkdtemp()
        try:
            snapshots = make_synthetic_snapshots(120)
            config = DEFAULT_FEATURE_CONFIG
            names, X, targets = build_training_data(snapshots, config)
            train_continuous_model("power_watts", names, X, targets["power_watts"], tmpdir)

            test_snap = snapshots[-1]
            result = predict_with_ml(test_snap, config, models_dir=tmpdir)
            preds = result["predictions"]
            self.assertTrue(result["is_trained"])
            self.assertIn("power_watts", preds)
            self.assertIsInstance(preds["power_watts"], float)
        finally:
            shutil.rmtree(tmpdir)

    def test_blend_predictions(self):
        # Under 14 days: pure statistical
        result = blend_predictions(100, 200, 10)
        self.assertEqual(result, 100)
        # At 14 days: 70/30 blend
        result = blend_predictions(100, 200, 30)
        self.assertAlmostEqual(result, 130.0)
        # At 60 days: 50/50
        result = blend_predictions(100, 200, 75)
        self.assertAlmostEqual(result, 150.0)
        # At 90+ days: 30/70
        result = blend_predictions(100, 200, 120)
        self.assertAlmostEqual(result, 170.0)

    def test_count_days_of_data(self, tmp_path=None):
        tmpdir = tempfile.mkdtemp()
        try:
            paths = PathConfig(data_dir=__import__("pathlib").Path(tmpdir))
            paths.ensure_dirs()
            for d in ["2026-02-05.json", "2026-02-06.json", "2026-02-07.json"]:
                with open(paths.daily_dir / d, "w") as f:
                    f.write("{}")
            self.assertEqual(count_days_of_data(paths), 3)
        finally:
            shutil.rmtree(tmpdir)

    def test_blend_predictions_none_ml(self):
        result = blend_predictions(150, None, 60)
        self.assertEqual(result, 150)


class TestHybridAnomalyDetection(unittest.TestCase):
    """Tests for the hybrid Autoencoder + IsolationForest anomaly detection."""

    def test_autoencoder_trains_and_reconstructs(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        import numpy as np

        from aria.engine.models.autoencoder import Autoencoder

        tmpdir = tempfile.mkdtemp()
        try:
            np.random.seed(42)
            X = np.random.randn(100, 48)
            ae = Autoencoder(hidden_layers=(24, 12, 24), max_iter=200)
            result = ae.train(X, tmpdir)
            self.assertNotIn("error", result)
            self.assertEqual(result["samples"], 100)
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "autoencoder.pkl")))
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "ae_scaler.pkl")))
        finally:
            shutil.rmtree(tmpdir)

    def test_autoencoder_reconstruction_error(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        import numpy as np

        from aria.engine.models.autoencoder import Autoencoder

        tmpdir = tempfile.mkdtemp()
        try:
            np.random.seed(42)
            X_normal = np.random.randn(100, 48)
            ae = Autoencoder(hidden_layers=(24, 12, 24), max_iter=200)
            ae.train(X_normal, tmpdir)

            # Normal data should have low reconstruction error
            normal_errors = ae.reconstruction_errors(X_normal[:10], tmpdir)
            # Anomalous data (10x scaled) should have higher reconstruction error
            X_anomaly = X_normal[:10] * 10
            anomaly_errors = ae.reconstruction_errors(X_anomaly, tmpdir)

            self.assertIsNotNone(normal_errors)
            self.assertIsNotNone(anomaly_errors)
            self.assertGreater(
                float(np.mean(anomaly_errors)),
                float(np.mean(normal_errors)),
                "Anomalous data should have higher reconstruction error than normal data",
            )
        finally:
            shutil.rmtree(tmpdir)

    def test_hybrid_isolation_forest_uses_ae_feature(self):
        if not HAS_SKLEARN:
            self.skipTest("sklearn not installed")
        import numpy as np

        tmpdir = tempfile.mkdtemp()
        try:
            np.random.seed(42)
            X = np.random.randn(100, 48)
            names = [f"feature_{i}" for i in range(48)]

            iso_model = IsolationForestModel()
            result = iso_model.train(names, X, tmpdir, use_autoencoder=True)
            self.assertNotIn("error", result)
            self.assertTrue(result["autoencoder_enabled"])
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "anomaly_config.pkl")))
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "autoencoder.pkl")))

            # Predict should work with autoencoder-augmented model
            pred = iso_model.predict(X[0], tmpdir)
            self.assertIn("is_anomaly", pred)
            self.assertIn("anomaly_score", pred)
        finally:
            shutil.rmtree(tmpdir)


# =============================================================================
# #199 — reference_model glob must match .pkl extension
# =============================================================================


def test_reference_model_glob_matches_save_extension(tmp_path):
    """#199: glob pattern must match the extension used when saving."""
    import glob

    from aria.engine.models.reference_model import MODEL_EXT, ReferenceModel  # noqa: F401

    # Verify constant exists and is .pkl
    assert MODEL_EXT == ".pkl", f"Expected .pkl, got {MODEL_EXT}"
    # Verify model file would be found by glob (create a fake .pkl and check glob finds it)
    fake_model = tmp_path / f"test_model{MODEL_EXT}"
    fake_model.write_bytes(b"fake")
    found = glob.glob(str(tmp_path / f"*{MODEL_EXT}"))
    assert len(found) == 1


# =============================================================================
# #200 — autoencoder missing model logs WARNING not silent None
# =============================================================================


def test_autoencoder_missing_model_logs_warning(tmp_path, caplog):
    """#200: missing model file must log WARNING, not return None silently."""
    import logging

    from aria.engine.models.autoencoder import Autoencoder

    ae = Autoencoder()
    with caplog.at_level(logging.WARNING):
        result = ae.reconstruction_errors([[0.5, 0.5, 0.5]], str(tmp_path))
    # Result should still be None (typed return) but a WARNING must be logged
    assert result is None
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "model" in m.lower() or "not" in m.lower() or "missing" in m.lower() or "autoencoder" in m.lower()
        for m in warning_msgs
    ), f"Expected WARNING about missing model, got: {caplog.records}"


# =============================================================================
# #201 — device_failure missing model logs WARNING not silent []
# =============================================================================


def test_device_failure_missing_model_logs_warning(tmp_path, caplog):
    """#201: missing model file must log WARNING, not return [] silently."""
    import logging

    from aria.engine.models.device_failure import predict_device_failures

    snapshots = [{"entities": {"unavailable_list": ["light.test"]}} for _ in range(5)]
    with caplog.at_level(logging.WARNING):
        result = predict_device_failures(snapshots, str(tmp_path))
    assert result == []
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("model" in m.lower() or "not" in m.lower() or "missing" in m.lower() for m in warning_msgs), (
        f"Expected WARNING about missing model, got: {caplog.records}"
    )


# =============================================================================
# #202 — gradient_boosting missing model logs WARNING not silent None
# =============================================================================


def test_gradient_boosting_missing_model_logs_warning(tmp_path, caplog):
    """#202: missing model file must log WARNING, not return None silently."""
    import logging

    from aria.engine.models.gradient_boosting import GradientBoostingModel

    model = GradientBoostingModel()
    model_path = str(tmp_path / "nonexistent.pkl")
    with caplog.at_level(logging.WARNING):
        result = model.predict([1.0, 2.0, 3.0], model_path)
    assert result is None
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("model" in m.lower() or "not" in m.lower() or "missing" in m.lower() for m in warning_msgs), (
        f"Expected WARNING about missing model, got: {caplog.records}"
    )


# =============================================================================
# #204 — autoencoder MLPRegressor convergence warning surfaced via logger
# =============================================================================


def test_autoencoder_convergence_warning_logged(tmp_path, caplog):
    """#204: ConvergenceWarning from MLPRegressor must be re-emitted via logger.warning()."""
    import logging

    import numpy as np

    from aria.engine.models.autoencoder import Autoencoder

    if not HAS_SKLEARN:
        pytest.skip("sklearn not installed")

    # Tiny data + max_iter=1 guarantees non-convergence
    np.random.seed(42)
    X = np.random.randn(20, 4)
    ae = Autoencoder(hidden_layers=(8, 4, 8), max_iter=1)

    with caplog.at_level(logging.WARNING, logger="aria.engine.models.autoencoder"):
        ae.train(X, str(tmp_path))

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("convergence" in m.lower() or "mlpregressor" in m.lower() for m in warning_msgs), (
        f"Expected convergence WARNING to be logged, got: {caplog.records}"
    )


class TestPersistAnomalyStatus:
    """Tests for _persist_anomaly_status logging (Fix 2 — bare except guard)."""

    def test_persist_anomaly_status_write_error_logs_warning(self, tmp_path, caplog):
        """When write fails (read-only dir), logs WARNING instead of silently swallowing."""
        import logging
        import stat

        models_dir = tmp_path / "models"
        models_dir.mkdir()
        # Make directory read-only so writes fail
        models_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            anomaly_result = {"samples": 100, "contamination": 0.05, "autoencoder_enabled": False}
            with caplog.at_level(logging.WARNING, logger="aria.engine.models.training"):
                _persist_anomaly_status(anomaly_result, str(models_dir))
            assert any("anomaly status" in r.message.lower() or "persist" in r.message.lower() for r in caplog.records)
        finally:
            models_dir.chmod(stat.S_IRWXU)

    def test_persist_anomaly_status_success_no_warning(self, tmp_path, caplog):
        """Successful write produces no warning."""
        import logging

        models_dir = tmp_path / "models"
        models_dir.mkdir()
        anomaly_result = {"samples": 100, "contamination": 0.05, "autoencoder_enabled": False}
        with caplog.at_level(logging.WARNING, logger="aria.engine.models.training"):
            _persist_anomaly_status(anomaly_result, str(models_dir))

        assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 0
        assert (models_dir / "isolation_forest_status.json").exists()

    def test_persist_anomaly_status_with_autoencoder(self, tmp_path):
        """Autoencoder-enabled result writes both status files."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        anomaly_result = {
            "samples": 200,
            "contamination": 0.05,
            "autoencoder_enabled": True,
            "ae_samples": 180,
            "hidden_layers": [16, 8, 16],
        }
        _persist_anomaly_status(anomaly_result, str(models_dir))
        assert (models_dir / "isolation_forest_status.json").exists()
        assert (models_dir / "autoencoder_status.json").exists()


if __name__ == "__main__":
    unittest.main()
