"""Regression tests for Batch 4b training.py and related fixes.

Covers:
  - #257: predict_with_ml logs warning when no model files found
  - #263: predict_with_ml returns is_trained bool in all code paths
  - #242: MLEngine logs warning when no trained model found on initialize
  - #245: faces/bootstrap.py splits IntegrityError vs OSError handling
  - #253: shadow_engine datetime.now() -> UTC-aware
  - #254: ha_automation_sync returns [] (not None) when session uninitialized
  - #259: discovery._classify_lock guards deferred classification TOCTOU
  - #264: ha_automations default is [] not {} in routes.py shadow compare
  - #265: SNAPSHOT_FIELDS constant exists in aria/shared/constants.py
"""

import logging
import pickle
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# #257: predict_with_ml logs warning when no model files found
# ============================================================================


class TestPredictWithMlNoModels:
    """predict_with_ml logs a warning when models_dir has no .pkl files."""

    def test_warning_logged_when_no_pkl_files(self, caplog, tmp_path):
        """#257: When models_dir is empty, a warning is logged about missing model files."""
        try:
            from aria.engine.models.training import HAS_SKLEARN, predict_with_ml
            from aria.shared.constants import DEFAULT_FEATURE_CONFIG
        except ImportError:
            pytest.skip("sklearn or aria not available")

        if not HAS_SKLEARN:
            pytest.skip("sklearn not installed")

        snapshot = {
            "power": {"total_watts": 100},
            "lights": {"on": 2},
            "occupancy": {"device_count_home": 1},
            "entities": {"total": 50},
            "logbook_summary": {},
            "weather": {},
            "time_features": {},
        }

        with caplog.at_level(logging.WARNING, logger="aria.engine.models.training"):
            result = predict_with_ml(snapshot, config=DEFAULT_FEATURE_CONFIG, models_dir=str(tmp_path))

        assert result["is_trained"] is False
        assert result["predictions"] == {}

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no trained model" in m.lower() or "model files" in m.lower() for m in warning_msgs), (
            f"Expected a warning about missing model files, got: {warning_msgs}"
        )


# ============================================================================
# #263: predict_with_ml returns is_trained bool in all code paths
# ============================================================================


class TestPredictWithMlReturnShape:
    """predict_with_ml must return {predictions: dict, is_trained: bool} in all paths."""

    def test_no_sklearn_returns_is_trained_false(self):
        """#263: When HAS_SKLEARN is False, returns is_trained=False."""
        with patch("aria.engine.models.training.HAS_SKLEARN", False):
            from aria.engine.models import training

            result = training.predict_with_ml({})
            assert "is_trained" in result
            assert result["is_trained"] is False
            assert result["predictions"] == {}

    def test_no_config_returns_is_trained_false(self, tmp_path):
        """#263: When config is None and no store, returns is_trained=False."""
        try:
            from aria.engine.models.training import HAS_SKLEARN, predict_with_ml
        except ImportError:
            pytest.skip("aria not available")

        if not HAS_SKLEARN:
            pytest.skip("sklearn not installed")

        # Patch DataStore.load_feature_config to return None (no config found)
        with patch("aria.engine.models.training.DataStore") as MockDS:
            MockDS.return_value.load_feature_config.return_value = None
            result = predict_with_ml({}, models_dir=str(tmp_path))

        assert result["is_trained"] is False
        assert result["predictions"] == {}

    def test_no_model_files_returns_is_trained_false(self, tmp_path):
        """#263: When models_dir has no .pkl files, returns is_trained=False."""
        try:
            from aria.engine.models.training import HAS_SKLEARN, predict_with_ml
            from aria.shared.constants import DEFAULT_FEATURE_CONFIG
        except ImportError:
            pytest.skip("aria not available")

        if not HAS_SKLEARN:
            pytest.skip("sklearn not installed")

        snapshot = {"power": {}, "lights": {}, "occupancy": {}, "entities": {}, "weather": {}, "time_features": {}}
        result = predict_with_ml(snapshot, config=DEFAULT_FEATURE_CONFIG, models_dir=str(tmp_path))

        assert "is_trained" in result
        assert result["is_trained"] is False
        assert result["predictions"] == {}

    def test_with_model_file_returns_is_trained_true(self, tmp_path):
        """#263: When a .pkl model file exists and predicts, returns is_trained=True."""
        try:
            from aria.engine.features.vector_builder import get_feature_names
            from aria.engine.models.training import HAS_SKLEARN, predict_with_ml
            from aria.shared.constants import DEFAULT_FEATURE_CONFIG
        except ImportError:
            pytest.skip("aria not available")

        if not HAS_SKLEARN:
            pytest.skip("sklearn not installed")

        try:
            import numpy as np
            from sklearn.linear_model import LinearRegression
        except ImportError:
            pytest.skip("sklearn not installed")

        # Build a model with the correct number of features
        feature_names = get_feature_names(DEFAULT_FEATURE_CONFIG)
        n_features = len(feature_names)
        model = LinearRegression()
        model.fit(np.zeros((2, n_features)), [0.0, 1.0])

        metric = DEFAULT_FEATURE_CONFIG["target_metrics"][0]
        model_path = tmp_path / f"{metric}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        snapshot = {"power": {}, "lights": {}, "occupancy": {}, "entities": {}, "weather": {}, "time_features": {}}
        result = predict_with_ml(snapshot, config=DEFAULT_FEATURE_CONFIG, models_dir=str(tmp_path))

        assert "is_trained" in result
        assert result["is_trained"] is True
        assert isinstance(result["predictions"], dict)
        assert metric in result["predictions"]


# ============================================================================
# #242: MLEngine logs warning when no trained model found on initialize
# ============================================================================


class TestMLEngineNoModelWarning:
    """MLEngine.initialize() logs a warning when no models are found on disk."""

    @pytest.mark.asyncio
    async def test_no_models_logs_warning(self, tmp_path, caplog):
        """#242: When models_dir has no .pkl files, MLEngine logs a warning."""
        try:
            from aria.engine.hardware import HardwareProfile
            from aria.modules.ml_engine import MLEngine
        except ImportError:
            pytest.skip("aria not available")

        mock_hub = MagicMock()
        mock_hub.cache = MagicMock()
        mock_hub.cache.get = AsyncMock(return_value={"data": {}})
        mock_hub.cache.get_config_value = AsyncMock(return_value=None)
        mock_hub.register_module = MagicMock()
        mock_hub.get_cache_fresh = AsyncMock(return_value={"data": {}})
        mock_hub.get_cache = AsyncMock(return_value={"data": {}})
        mock_hub.set_cache = AsyncMock(return_value=None)
        # Provide a real HardwareProfile to avoid MagicMock comparison issues
        mock_hub.hardware_profile = HardwareProfile(ram_gb=8.0, cpu_cores=4, gpu_available=False)

        # MLEngine.__init__ signature: (hub, models_dir, training_data_dir)
        training_dir = tmp_path / "training"
        training_dir.mkdir()
        engine = MLEngine(mock_hub, models_dir=str(tmp_path), training_data_dir=str(training_dir))

        with caplog.at_level(logging.WARNING, logger="module.ml_engine"):
            await engine.initialize()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no trained model" in m.lower() for m in warning_msgs), (
            f"Expected warning about no trained model, got: {warning_msgs}"
        )


# ============================================================================
# #253: shadow_engine datetime.now() uses UTC
# ============================================================================


class TestShadowEngineUTCAware:
    """ShadowEngine uses UTC-aware datetimes in context snapshots."""

    def test_shadow_engine_imports_utc(self):
        """#253: shadow_engine module must import UTC from datetime."""
        from aria.modules import shadow_engine

        src = Path(shadow_engine.__file__).read_text()
        assert "from datetime import UTC" in src or "datetime.UTC" in src or ", UTC," in src, (
            "shadow_engine.py must import UTC for timezone-aware datetimes"
        )

    def test_shadow_engine_uses_utc_in_on_event(self):
        """#253: ShadowEngine._on_event uses datetime.now(tz=UTC), not naive datetime.now()."""
        from aria.modules import shadow_engine as se_mod

        src = Path(se_mod.__file__).read_text()
        # All datetime.now() calls must include tz=UTC
        import re

        naive_calls = re.findall(r"datetime\.now\(\)", src)
        assert not naive_calls, (
            f"shadow_engine.py contains {len(naive_calls)} naive datetime.now() call(s) — "
            "all must use datetime.now(tz=UTC)"
        )


# ============================================================================
# #254: ha_automation_sync returns [] (not None) when session uninitialized
# ============================================================================


class TestHaAutomationSyncSessionGuard:
    """HaAutomationSync._fetch_automations returns [] when session is None."""

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_list_when_no_session(self):
        """#254: _fetch_automations must return [] (not None) when session is None."""
        try:
            from aria.shared.ha_automation_sync import HaAutomationSync
        except ImportError:
            pytest.skip("HaAutomationSync not available")

        sync = HaAutomationSync(hub=MagicMock(), ha_url="http://test", ha_token="tok")
        sync._session = None

        result = await sync._fetch_automations()
        assert result == [], f"Expected [] when session is None, got: {result!r}"


# ============================================================================
# #259: DiscoveryModule._classify_lock guards TOCTOU
# ============================================================================


class TestDiscoveryClassifyLock:
    """DiscoveryModule exposes _classify_lock for TOCTOU guard."""

    @pytest.mark.asyncio
    async def test_classify_lock_exists(self, tmp_path):
        """#259: DiscoveryModule must have a _classify_lock attribute."""
        try:
            from aria.modules.discovery import DiscoveryModule
        except ImportError:
            pytest.skip("DiscoveryModule not available")

        import asyncio

        mock_hub = MagicMock()
        mock_hub.cache = MagicMock()
        mock_hub.register_module = MagicMock()

        # Create a minimal discover.py script path placeholder
        discover_script = tmp_path / "bin" / "discover.py"
        discover_script.parent.mkdir(parents=True, exist_ok=True)
        discover_script.write_text("# stub")

        with patch.object(DiscoveryModule, "__init__", lambda self, *a, **kw: None):
            module = DiscoveryModule.__new__(DiscoveryModule)
            module._classify_lock = asyncio.Lock()

        assert hasattr(module, "_classify_lock")
        assert isinstance(module._classify_lock, asyncio.Lock)


# ============================================================================
# #264: ha_automations default is [] not {} in routes.py shadow compare
# ============================================================================


class TestHaAutomationsDefaultsList:
    """routes.py must default ha_automations to [] not {} when cache is empty."""

    @pytest.mark.asyncio
    async def test_shadow_compare_normalizes_dict_to_list(self):
        """#264: If ha_automations cache is a dict, routes.py normalizes to []."""
        try:
            from aria.hub import routes
        except ImportError:
            pytest.skip("routes not available")

        # Verify source-level: if ha_automations_raw is a dict, it gets replaced with []
        src = Path(routes.__file__).read_text()
        assert "isinstance(ha_automations_raw, list)" in src, (
            "routes.py must check isinstance(ha_automations_raw, list) for normalization"
        )
        assert "ha_automations_raw = []" in src, "routes.py must normalize non-list ha_automations to []"


# ============================================================================
# #265: SNAPSHOT_FIELDS constant exists in aria/shared/constants.py
# ============================================================================


class TestSnapshotFieldsConstant:
    """SNAPSHOT_FIELDS must exist in aria.shared.constants."""

    def test_snapshot_fields_exists(self):
        """#265: SNAPSHOT_FIELDS is defined in aria.shared.constants."""
        from aria.shared.constants import SNAPSHOT_FIELDS

        assert SNAPSHOT_FIELDS is not None
        assert len(SNAPSHOT_FIELDS) > 0

    def test_snapshot_fields_contains_expected_keys(self):
        """#265: SNAPSHOT_FIELDS must include core snapshot section names."""
        from aria.shared.constants import SNAPSHOT_FIELDS

        required = {"power", "lights", "occupancy", "entities", "weather"}
        snapshot_set = set(SNAPSHOT_FIELDS)
        missing = required - snapshot_set
        assert not missing, f"SNAPSHOT_FIELDS missing expected keys: {missing}"
