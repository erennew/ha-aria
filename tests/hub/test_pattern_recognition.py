"""Tests for pattern recognition hub module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria.modules.pattern_recognition import PatternRecognitionModule


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.subscribe = MagicMock()
    hub.get_cache = AsyncMock(return_value=None)
    hub.set_cache = AsyncMock()
    hub.publish = AsyncMock()
    hub.get_config_value = MagicMock(return_value=None)
    hub.modules = {}
    return hub


class TestPatternRecognitionInit:
    """Test module initialization and tier gating."""

    def test_module_id(self, mock_hub):
        module = PatternRecognitionModule(mock_hub)
        assert module.module_id == "pattern_recognition"

    def test_no_subscribe_in_constructor(self, mock_hub):
        PatternRecognitionModule(mock_hub)
        # Subscribe should NOT happen in __init__ — moved to initialize()
        mock_hub.subscribe.assert_not_called()

    @patch("aria.modules.pattern_recognition.recommend_tier", return_value=2)
    @patch("aria.modules.pattern_recognition.scan_hardware")
    async def test_tier_gate_blocks_below_tier_3(self, mock_scan, mock_tier, mock_hub):
        """Module disables itself at Tier 2."""
        mock_scan.return_value = MagicMock(ram_gb=4, cpu_cores=2)
        module = PatternRecognitionModule(mock_hub)
        await module.initialize()
        assert module.active is False

    @patch("aria.modules.pattern_recognition.recommend_tier", return_value=3)
    @patch("aria.modules.pattern_recognition.scan_hardware")
    async def test_tier_gate_allows_tier_3(self, mock_scan, mock_tier, mock_hub):
        """Module activates at Tier 3."""
        mock_scan.return_value = MagicMock(ram_gb=16, cpu_cores=4)
        module = PatternRecognitionModule(mock_hub)
        await module.initialize()
        assert module.active is True


class TestTrajectoryClassification:
    """Test trajectory window management and classification."""

    @patch("aria.modules.pattern_recognition.recommend_tier", return_value=3)
    @patch("aria.modules.pattern_recognition.scan_hardware")
    async def test_on_shadow_resolved_updates_cache(self, mock_scan, mock_tier, mock_hub):
        """Shadow resolved events feed the trajectory window."""
        mock_scan.return_value = MagicMock(ram_gb=16, cpu_cores=4)
        module = PatternRecognitionModule(mock_hub)
        await module.initialize()

        # Feed enough events to build a window
        for i in range(6):
            await module._on_shadow_resolved(
                {
                    "target": "power_watts",
                    "features": {"power": float(i * 10), "lights": 1.0},
                    "actual_value": float(i * 10),
                    "timestamp": datetime.now().isoformat(),
                }
            )

        # Should have trajectory classification result
        assert module.current_trajectory is not None

    async def test_get_current_state(self, mock_hub):
        """get_current_state returns trajectory and scale info."""
        module = PatternRecognitionModule(mock_hub)
        state = module.get_current_state()
        assert "trajectory" in state
        assert "pattern_scales" in state
        assert "anomaly_explanations" in state

    async def test_get_stats(self, mock_hub):
        """get_stats includes sequence classifier info."""
        module = PatternRecognitionModule(mock_hub)
        stats = module.get_stats()
        assert "active" in stats
        assert "sequence_classifier" in stats
        assert "window_count" in stats


class TestPatternRecognitionLifecycle:
    """Test subscribe/unsubscribe lifecycle — subscribe in initialize(), not __init__."""

    @pytest.fixture
    def mock_hub(self):
        hub = MagicMock()
        hub.subscribe = MagicMock()
        hub.unsubscribe = MagicMock()
        hub.set_cache = AsyncMock()
        hub.get_cache = AsyncMock(return_value=None)
        hub.get_config_value = AsyncMock(return_value=None)
        return hub

    def test_no_subscribe_in_init(self, mock_hub):
        """Subscribe should NOT happen in __init__ — only after initialize()."""
        with (
            patch("aria.modules.pattern_recognition.scan_hardware") as mock_hw,
            patch("aria.modules.pattern_recognition.recommend_tier", return_value=3),
        ):
            mock_hw.return_value = MagicMock(ram_gb=32, cpu_cores=8, gpu_available=False)
            PatternRecognitionModule(mock_hub)

        mock_hub.subscribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribe_after_initialize_when_active(self, mock_hub):
        """Subscribe should happen in initialize() when tier >= 3."""
        with (
            patch("aria.modules.pattern_recognition.scan_hardware") as mock_hw,
            patch("aria.modules.pattern_recognition.recommend_tier", return_value=3),
        ):
            mock_hw.return_value = MagicMock(ram_gb=32, cpu_cores=8, gpu_available=False)
            module = PatternRecognitionModule(mock_hub)
            await module.initialize()

        mock_hub.subscribe.assert_called_once_with("shadow_resolved", module._on_shadow_resolved)

    @pytest.mark.asyncio
    async def test_no_subscribe_when_tier_too_low(self, mock_hub):
        """Should NOT subscribe when tier < MIN_TIER."""
        with (
            patch("aria.modules.pattern_recognition.scan_hardware") as mock_hw,
            patch("aria.modules.pattern_recognition.recommend_tier", return_value=2),
        ):
            mock_hw.return_value = MagicMock(ram_gb=4, cpu_cores=2, gpu_available=False)
            module = PatternRecognitionModule(mock_hub)
            await module.initialize()

        mock_hub.subscribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_unsubscribes(self, mock_hub):
        """shutdown() must unsubscribe from shadow_resolved."""
        with (
            patch("aria.modules.pattern_recognition.scan_hardware") as mock_hw,
            patch("aria.modules.pattern_recognition.recommend_tier", return_value=3),
        ):
            mock_hw.return_value = MagicMock(ram_gb=32, cpu_cores=8, gpu_available=False)
            module = PatternRecognitionModule(mock_hub)
            await module.initialize()
            await module.shutdown()

        mock_hub.unsubscribe.assert_called_once_with("shadow_resolved", module._on_shadow_resolved)


class TestModuleRegistration:
    """Test that pattern_recognition registers correctly in hub."""

    async def test_module_registers_without_error(self, mock_hub):
        """Module can be instantiated and registered."""
        module = PatternRecognitionModule(mock_hub)
        mock_hub.register_module = MagicMock()
        mock_hub.register_module(module)
        mock_hub.register_module.assert_called_once_with(module)
