"""Integration tests for Phase 4 — transfer engine and attention explainer.

Tests the full flows:
  organic discovery → transfer candidate generation → shadow testing → promotion
  attention explainer train → explain → contrastive output
"""

import importlib.util
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from aria.engine.transfer import TransferCandidate, TransferType, compute_jaccard_similarity
from aria.engine.transfer_generator import generate_transfer_candidates
from aria.modules.transfer_engine import TransferEngineModule

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.subscribe = MagicMock()
    hub.unsubscribe = MagicMock()
    hub.get_cache = AsyncMock(return_value=None)
    hub.set_cache = AsyncMock()
    hub.publish = AsyncMock()
    hub.get_config_value = MagicMock(return_value=None)
    hub.get_module = MagicMock(return_value=None)
    hub.modules = {}
    return hub


class TestTransferPipeline:
    """End-to-end transfer candidate lifecycle."""

    def test_jaccard_used_for_structural_similarity(self):
        """Jaccard similarity correctly identifies matching compositions."""
        kitchen = {"light", "binary_sensor"}
        bedroom = {"light", "binary_sensor"}
        garage = {"sensor", "cover"}

        assert compute_jaccard_similarity(kitchen, bedroom) == 1.0
        assert compute_jaccard_similarity(kitchen, garage) == 0.0

    def test_candidate_full_lifecycle(self):
        """hypothesis → testing → promoted via shadow results."""
        tc = TransferCandidate(
            source_capability="kitchen_lighting",
            target_context="bedroom",
            transfer_type=TransferType.ROOM_TO_ROOM,
            similarity_score=0.72,
            source_entities=["light.kitchen_1"],
            target_entities=["light.bedroom_1"],
        )
        assert tc.state == "hypothesis"

        # First shadow result transitions to testing
        tc.record_shadow_result(hit=True)
        assert tc.state == "testing"

        # Accumulate hits
        for _ in range(19):
            tc.record_shadow_result(hit=True)

        # Not promoted yet — min_days not met
        tc.check_promotion(min_days=7, min_hit_rate=0.6)
        assert tc.state == "testing"

        # Fast-forward testing_since
        tc.testing_since = datetime(2026, 2, 9)
        tc.check_promotion(min_days=7, min_hit_rate=0.6)
        assert tc.state == "promoted"

    def test_generator_produces_candidates_for_similar_rooms(self):
        """Room-to-room generation from organic capabilities."""
        capabilities = {
            "kitchen_lights": {
                "entities": ["light.kitchen_1", "binary_sensor.kitchen_motion"],
                "layer": "domain",
                "status": "promoted",
                "source": "organic",
            },
            "bedroom_lights": {
                "entities": ["light.bedroom_1", "binary_sensor.bedroom_motion"],
                "layer": "domain",
                "status": "candidate",
                "source": "organic",
            },
        }
        entities_cache = {
            "light.kitchen_1": {
                "entity_id": "light.kitchen_1",
                "domain": "light",
                "area_id": "kitchen",
            },
            "binary_sensor.kitchen_motion": {
                "entity_id": "binary_sensor.kitchen_motion",
                "domain": "binary_sensor",
                "area_id": "kitchen",
                "device_class": "motion",
            },
            "light.bedroom_1": {
                "entity_id": "light.bedroom_1",
                "domain": "light",
                "area_id": "bedroom",
            },
            "binary_sensor.bedroom_motion": {
                "entity_id": "binary_sensor.bedroom_motion",
                "domain": "binary_sensor",
                "area_id": "bedroom",
                "device_class": "motion",
            },
        }

        candidates = generate_transfer_candidates(capabilities, entities_cache, min_similarity=0.5)
        assert len(candidates) >= 1

    @patch("aria.modules.transfer_engine.recommend_tier", return_value=2)
    @patch("aria.modules.transfer_engine.scan_hardware")
    async def test_tier_2_disables_transfer(self, mock_scan, mock_tier, mock_hub):
        """Tier 2 hardware disables transfer engine."""
        mock_scan.return_value = MagicMock(ram_gb=4, cpu_cores=2)
        module = TransferEngineModule(mock_hub)
        await module.initialize()
        assert module.active is False


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")
class TestAttentionPipeline:
    """End-to-end attention explainer tests (torch required)."""

    def test_train_explain_cycle(self):
        """Train on normal data, explain anomaly, get contrastive output."""
        from aria.engine.attention_explainer import AttentionExplainer

        explainer = AttentionExplainer(n_features=5, sequence_length=6, hidden_dim=16)
        np.random.seed(42)
        x_train = np.random.normal(0, 1, (30, 6, 5))
        result = explainer.train(x_train, epochs=5)
        assert result["trained"] is True

        # Anomalous window
        anomaly = np.zeros((6, 5))
        anomaly[:, 0] = 10.0

        explanation = explainer.explain(
            anomaly,
            feature_names=["power", "lights", "motion", "temp", "humidity"],
        )
        assert len(explanation["feature_contributions"]) > 0
        assert len(explanation["temporal_attention"]) == 6
        assert explanation["contrastive_explanation"] is not None
        assert "power" in explanation["contrastive_explanation"]
