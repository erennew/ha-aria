"""Unit tests for AutomationGeneratorModule.

Tests the hub module that coordinates pattern/gap detection results
through template engine → LLM refiner → validator → shadow comparison
pipeline, storing final suggestions in cache.

Covers: Task 27 (hub module) and Task 29 (combined scoring).
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aria.automation.models import ChainLink, DetectionResult, ShadowResult
from aria.modules.automation_generator import (
    AutomationGeneratorModule,
    compute_combined_score,
)

# ============================================================================
# Mock Hub
# ============================================================================


class MockHub:
    """Lightweight hub mock for generator tests."""

    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}
        self._running = True
        self._scheduled_tasks: list[dict[str, Any]] = []
        self._published_events: list[dict[str, Any]] = []
        self.logger = MagicMock()
        self.modules = {}
        self.entity_graph = MagicMock()
        # EntityGraph defaults: has_entity → True, entities_in_area → []
        self.entity_graph.has_entity = MagicMock(return_value=True)
        self.entity_graph.entities_in_area = MagicMock(return_value=[])
        self.entity_graph.get_area = MagicMock(return_value=None)

    async def set_cache(self, category: str, data: Any, metadata: dict | None = None):
        self._cache[category] = {
            "data": data,
            "metadata": metadata,
            "last_updated": datetime.now().isoformat(),
        }

    async def get_cache(self, category: str) -> dict[str, Any] | None:
        return self._cache.get(category)

    async def get_cache_fresh(self, category: str, max_age=None, caller="") -> dict[str, Any] | None:
        return self._cache.get(category)

    def is_running(self) -> bool:
        return self._running

    async def schedule_task(self, **kwargs):
        self._scheduled_tasks.append(kwargs)

    def register_module(self, mod):
        self.modules[mod.module_id] = mod

    def get_module(self, module_id: str):
        return self.modules.get(module_id)

    async def publish(self, event_type: str, data: dict[str, Any]):
        self._published_events.append({"event_type": event_type, "data": data})


# ============================================================================
# Test Data Helpers
# ============================================================================


def make_detection(  # noqa: PLR0913
    source="pattern",
    trigger="binary_sensor.motion_kitchen",
    actions=None,
    area_id="kitchen",
    confidence=0.85,
    recency_weight=0.7,
    observation_count=12,
    day_type="workday",
) -> DetectionResult:
    """Build a DetectionResult for testing."""
    if actions is None:
        actions = ["light.kitchen_main"]
    return DetectionResult(
        source=source,
        trigger_entity=trigger,
        action_entities=actions,
        entity_chain=[
            ChainLink(entity_id=trigger, state="on", offset_seconds=0),
        ],
        area_id=area_id,
        confidence=confidence,
        recency_weight=recency_weight,
        observation_count=observation_count,
        first_seen="2026-01-01T00:00:00",
        last_seen="2026-02-01T00:00:00",
        day_type=day_type,
    )


def make_pattern_cache(detections: list[DetectionResult] | None = None) -> dict:
    """Build a patterns cache dict from DetectionResult objects."""
    if detections is None:
        detections = [make_detection(source="pattern")]
    return {
        "detections": [
            {
                "source": d.source,
                "trigger_entity": d.trigger_entity,
                "action_entities": d.action_entities,
                "entity_chain": [
                    {"entity_id": c.entity_id, "state": c.state, "offset_seconds": c.offset_seconds}
                    for c in d.entity_chain
                ],
                "area_id": d.area_id,
                "confidence": d.confidence,
                "recency_weight": d.recency_weight,
                "observation_count": d.observation_count,
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
                "day_type": d.day_type,
            }
            for d in detections
        ],
    }


def make_gap_cache(detections: list[DetectionResult] | None = None) -> dict:
    """Build a gaps cache dict from DetectionResult objects."""
    if detections is None:
        detections = [make_detection(source="gap", trigger="binary_sensor.door_front")]
    return {
        "detections": [
            {
                "source": d.source,
                "trigger_entity": d.trigger_entity,
                "action_entities": d.action_entities,
                "entity_chain": [
                    {"entity_id": c.entity_id, "state": c.state, "offset_seconds": c.offset_seconds}
                    for c in d.entity_chain
                ],
                "area_id": d.area_id,
                "confidence": d.confidence,
                "recency_weight": d.recency_weight,
                "observation_count": d.observation_count,
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
                "day_type": d.day_type,
            }
            for d in detections
        ],
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def hub():
    return MockHub()


@pytest.fixture
def module(hub):
    """Create an AutomationGeneratorModule with mock hub."""
    return AutomationGeneratorModule(hub=hub, top_n=5, min_confidence=0.6)


# ============================================================================
# Task 29: Combined Scoring
# ============================================================================


class TestCombinedScoring:
    """Test compute_combined_score with pattern × 0.5 + gap × 0.3 + recency × 0.2."""

    def test_pattern_source_scoring(self):
        """Pattern source uses confidence * 0.5 + 0 * 0.3 + recency * 0.2."""
        d = make_detection(source="pattern", confidence=0.9, recency_weight=0.8)
        score = compute_combined_score(d)
        expected = 0.9 * 0.5 + 0.0 * 0.3 + 0.8 * 0.2
        assert abs(score - expected) < 1e-9

    def test_gap_source_scoring(self):
        """Gap source uses 0 * 0.5 + confidence * 0.3 + recency * 0.2."""
        d = make_detection(source="gap", confidence=0.7, recency_weight=0.5)
        score = compute_combined_score(d)
        expected = 0.0 * 0.5 + 0.7 * 0.3 + 0.5 * 0.2
        assert abs(score - expected) < 1e-9

    def test_max_scores(self):
        """Perfect confidence + recency for pattern source."""
        d = make_detection(source="pattern", confidence=1.0, recency_weight=1.0)
        score = compute_combined_score(d)
        expected = 1.0 * 0.5 + 0.0 * 0.3 + 1.0 * 0.2
        assert abs(score - expected) < 1e-9
        assert score == 0.7

    def test_zero_scores(self):
        """Zero confidence and recency = 0.0."""
        d = make_detection(source="pattern", confidence=0.0, recency_weight=0.0)
        score = compute_combined_score(d)
        assert score == 0.0

    def test_combined_score_stored_on_detection(self):
        """compute_combined_score sets the combined_score field."""
        d = make_detection(source="pattern", confidence=0.8, recency_weight=0.6)
        score = compute_combined_score(d)
        assert score == d.combined_score

    def test_mixed_source_gap_gets_gap_weight(self):
        """Gap detections use gap weight (0.3), not pattern weight (0.5)."""
        d_gap = make_detection(source="gap", confidence=0.8, recency_weight=0.6)
        d_pattern = make_detection(source="pattern", confidence=0.8, recency_weight=0.6)
        gap_score = compute_combined_score(d_gap)
        pattern_score = compute_combined_score(d_pattern)
        # Pattern should score higher with same confidence
        assert pattern_score > gap_score


# ============================================================================
# Task 27: Module Construction & Lifecycle
# ============================================================================


class TestModuleConstruction:
    """Test AutomationGeneratorModule constructor and lifecycle."""

    def test_module_id(self, module):
        """Module ID should be 'automation_generator'."""
        assert module.module_id == "automation_generator"

    def test_constructor_stores_config(self, module):
        """Constructor stores top_n and min_confidence."""
        assert module.top_n == 5
        assert module.min_confidence == 0.6

    def test_default_top_n(self, hub):
        """Default top_n is 10."""
        mod = AutomationGeneratorModule(hub=hub)
        assert mod.top_n == 10

    def test_default_min_confidence(self, hub):
        """Default min_confidence is 0.7."""
        mod = AutomationGeneratorModule(hub=hub)
        assert mod.min_confidence == 0.7

    def test_has_capabilities(self, module):
        """Module declares capabilities."""
        assert len(module.CAPABILITIES) >= 1
        assert module.CAPABILITIES[0].id == "automation_generator"

    @pytest.mark.asyncio
    async def test_initialize_schedules_task(self, module, hub):
        """initialize() schedules periodic generation."""
        await module.initialize()
        assert len(hub._scheduled_tasks) >= 1
        task_ids = [t.get("task_id") for t in hub._scheduled_tasks]
        assert "automation_generator_cycle" in task_ids

    @pytest.mark.asyncio
    async def test_shutdown_is_safe(self, module):
        """shutdown() completes without error."""
        await module.shutdown()


# ============================================================================
# Task 27: generate_suggestions Pipeline
# ============================================================================


class TestGenerateSuggestions:
    """Test the full generate_suggestions pipeline."""

    @pytest.mark.asyncio
    async def test_no_caches_returns_empty(self, module, hub):
        """No pattern/gap caches → empty list."""
        result = await module.generate_suggestions()
        assert result == []

    @pytest.mark.asyncio
    async def test_pattern_cache_only(self, module, hub):
        """Pattern cache alone produces suggestions."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            # LLM refiner returns input unchanged
            mock_refine.side_effect = lambda auto, **kw: auto
            result = await module.generate_suggestions()

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_gap_cache_only(self, module, hub):
        """Gap cache alone produces suggestions."""
        det = make_detection(source="gap", confidence=0.75)
        await hub.set_cache("gaps", make_gap_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            result = await module.generate_suggestions()

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_both_caches_combined(self, module, hub):
        """Both pattern and gap caches are combined."""
        p_det = make_detection(source="pattern", confidence=0.9)
        g_det = make_detection(source="gap", trigger="binary_sensor.door", confidence=0.8)
        await hub.set_cache("patterns", make_pattern_cache([p_det]))
        await hub.set_cache("gaps", make_gap_cache([g_det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            result = await module.generate_suggestions()

        assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_top_n_limits_output(self, hub):
        """Only top_n suggestions are produced."""
        mod = AutomationGeneratorModule(hub=hub, top_n=2, min_confidence=0.0)
        detections = [
            make_detection(source="pattern", trigger=f"sensor.s{i}", confidence=0.5 + i * 0.05) for i in range(5)
        ]
        await hub.set_cache("patterns", make_pattern_cache(detections))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            result = await mod.generate_suggestions()

        assert len(result) <= 2

    @pytest.mark.asyncio
    async def test_min_confidence_filters(self, hub):
        """Detections below min_confidence are excluded."""
        mod = AutomationGeneratorModule(hub=hub, top_n=10, min_confidence=0.8)
        detections = [
            make_detection(source="pattern", trigger="sensor.low", confidence=0.3),
            make_detection(source="pattern", trigger="sensor.high", confidence=0.9),
        ]
        await hub.set_cache("patterns", make_pattern_cache(detections))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            result = await mod.generate_suggestions()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_stores_in_cache(self, module, hub):
        """Suggestions are stored in automation_suggestions cache."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            await module.generate_suggestions()

        cached = await hub.get_cache("automation_suggestions")
        assert cached is not None
        assert "suggestions" in cached["data"]

    @pytest.mark.asyncio
    async def test_validator_failures_excluded(self, module, hub):
        """Suggestions that fail validation are excluded."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (False, ["Missing required field: id"])
            result = await module.generate_suggestions()

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_shadow_duplicate_excluded(self, module, hub):
        """Suggestions flagged as duplicate by shadow comparison are excluded."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="duplicate",
                duplicate_score=0.95,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="Exact duplicate",
            )
            result = await module.generate_suggestions()

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_shadow_new_included(self, module, hub):
        """Suggestions flagged as 'new' by shadow comparison are included."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="No match found",
            )
            result = await module.generate_suggestions()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_shadow_gap_fill_included(self, module, hub):
        """Suggestions flagged as 'gap_fill' by shadow comparison are included."""
        det = make_detection(source="gap", confidence=0.75)
        await hub.set_cache("gaps", make_gap_cache([det]))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="gap_fill",
                duplicate_score=0.3,
                conflicting_automation=None,
                gap_source_automation="auto_x",
                reason="Fills gap",
            )
            result = await module.generate_suggestions()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_llm_refiner_called(self, module, hub):
        """LLM refiner is invoked on each template output."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            await module.generate_suggestions()

        assert mock_refine.call_count >= 1

    @pytest.mark.asyncio
    async def test_llm_refiner_failure_uses_template(self, module, hub):
        """If LLM refiner fails, template output is used unchanged."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = Exception("LLM timeout")
            with patch("aria.modules.automation_generator.validate_automation") as mock_validate:
                mock_validate.return_value = (True, [])
                with patch("aria.modules.automation_generator.compare_candidate") as mock_shadow:
                    mock_shadow.return_value = ShadowResult(
                        candidate={},
                        status="new",
                        duplicate_score=0.0,
                        conflicting_automation=None,
                        gap_source_automation=None,
                        reason="New",
                    )
                    result = await module.generate_suggestions()

        # Should still produce a suggestion using unrefined template
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_sorted_by_combined_score(self, module, hub):
        """Results are sorted by combined score descending."""
        detections = [
            make_detection(source="pattern", trigger="sensor.low", confidence=0.3, recency_weight=0.1),
            make_detection(source="pattern", trigger="sensor.high", confidence=0.95, recency_weight=0.9),
        ]
        await hub.set_cache("patterns", make_pattern_cache(detections))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="New",
            )
            result = await module.generate_suggestions()

        if len(result) >= 2:
            assert result[0]["combined_score"] >= result[1]["combined_score"]


# ============================================================================
# Task 27: Event Handling
# ============================================================================


class TestEventHandling:
    """Test on_event triggers suggestion regeneration."""

    @pytest.mark.asyncio
    async def test_patterns_update_triggers_generation(self, module, hub):
        """cache_updated for 'patterns' triggers generate_suggestions."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            await module.on_event("cache_updated", {"category": "patterns"})

        cached = await hub.get_cache("automation_suggestions")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_gaps_update_triggers_generation(self, module, hub):
        """cache_updated for 'gaps' triggers generate_suggestions."""
        det = make_detection(source="gap", confidence=0.75)
        await hub.set_cache("gaps", make_gap_cache([det]))

        with patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine:
            mock_refine.side_effect = lambda auto, **kw: auto
            await module.on_event("cache_updated", {"category": "gaps"})

        cached = await hub.get_cache("automation_suggestions")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_unrelated_cache_update_ignored(self, module, hub):
        """cache_updated for 'entities' does NOT trigger generation."""
        await module.on_event("cache_updated", {"category": "entities"})

        cached = await hub.get_cache("automation_suggestions")
        assert cached is None

    @pytest.mark.asyncio
    async def test_non_cache_event_ignored(self, module, hub):
        """Non cache_updated events are ignored."""
        await module.on_event("state_changed", {"entity_id": "light.kitchen"})

        cached = await hub.get_cache("automation_suggestions")
        assert cached is None


# ============================================================================
# Task 27: Suggestion Output Format
# ============================================================================


class TestSuggestionFormat:
    """Test the structure of generated suggestions."""

    @pytest.mark.asyncio
    async def test_suggestion_has_required_fields(self, module, hub):
        """Each suggestion has required fields."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="New",
            )
            result = await module.generate_suggestions()

        assert len(result) >= 1
        s = result[0]
        assert "suggestion_id" in s
        assert "automation_yaml" in s
        assert "combined_score" in s
        assert "shadow_status" in s
        assert "source" in s
        assert "status" in s
        assert s["status"] == "pending"

    @pytest.mark.asyncio
    async def test_suggestion_preserves_existing_status(self, module, hub):
        """Regeneration preserves approved/rejected status from prior cache."""
        det = make_detection(source="pattern", confidence=0.85)
        await hub.set_cache("patterns", make_pattern_cache([det]))

        # First generation
        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="New",
            )
            result1 = await module.generate_suggestions()

        if not result1:
            pytest.skip("No suggestions generated")

        sid = result1[0]["suggestion_id"]

        # Mark as approved in cache
        cached = await hub.get_cache("automation_suggestions")
        for s in cached["data"]["suggestions"]:
            if s["suggestion_id"] == sid:
                s["status"] = "approved"
        await hub.set_cache("automation_suggestions", cached["data"])

        # Regenerate
        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="New",
            )
            result2 = await module.generate_suggestions()

        matched = [s for s in result2 if s["suggestion_id"] == sid]
        if matched:
            assert matched[0]["status"] == "approved"


# ============================================================================
# Task 32: Health Cache + Observability
# ============================================================================


class TestHealthCacheUpdate:
    """Tests for automation_system_health cache category."""

    @pytest.fixture
    def hub(self):
        """Create a MockHub for health cache tests."""
        return MockHub()

    @pytest.fixture
    def module(self, hub):
        """Create a generator module for health cache tests."""
        return AutomationGeneratorModule(hub, top_n=5, min_confidence=0.5)

    @pytest.mark.asyncio
    async def test_health_cache_populated_after_generation(self, hub, module):
        """generate_suggestions() writes automation_system_health cache."""
        # Seed pattern cache with a valid detection
        det = make_detection(source="pattern", confidence=0.9)
        await hub.set_cache("patterns", make_pattern_cache([det]))
        await hub.set_cache("gaps", {"detections": []})

        with (
            patch("aria.modules.automation_generator.refine_automation", new_callable=AsyncMock) as mock_refine,
            patch("aria.modules.automation_generator.validate_automation") as mock_validate,
            patch("aria.modules.automation_generator.compare_candidate") as mock_shadow,
        ):
            mock_refine.side_effect = lambda auto, **kw: auto
            mock_validate.return_value = (True, [])
            mock_shadow.return_value = ShadowResult(
                candidate={},
                status="new",
                duplicate_score=0.0,
                conflicting_automation=None,
                gap_source_automation=None,
                reason="New automation",
            )
            await module.generate_suggestions()

        health = await hub.get_cache("automation_system_health")
        assert health is not None
        data = health["data"]
        assert data["generator_loaded"] is True
        assert data["suggestions_total"] >= 1
        assert "last_generation" in data
        assert "suggestions_pending" in data

    @pytest.mark.asyncio
    async def test_health_cache_counts_by_status(self, hub, module):
        """Health cache correctly counts pending/approved/rejected."""
        # Pre-populate existing suggestions with mixed statuses
        existing = [
            {"suggestion_id": "s1", "status": "approved", "created_at": "2026-01-01"},
            {"suggestion_id": "s2", "status": "rejected", "created_at": "2026-01-01"},
        ]
        await hub.set_cache("automation_suggestions", {"suggestions": existing, "count": 2})

        # Empty caches for the generation run
        await hub.set_cache("patterns", {"detections": []})
        await hub.set_cache("gaps", {"detections": []})

        # No detections means no new suggestions — just health update
        await module.generate_suggestions()

        health = await hub.get_cache("automation_system_health")
        assert health is not None
        data = health["data"]
        assert data["suggestions_total"] == 0
        assert data["suggestions_pending"] == 0

    @pytest.mark.asyncio
    async def test_health_cache_failure_is_non_fatal(self, hub, module):
        """Health cache update failure doesn't break suggestion generation."""
        await hub.set_cache("patterns", {"detections": []})
        await hub.set_cache("gaps", {"detections": []})

        # Make set_cache fail only for health updates
        original_set_cache = hub.set_cache

        async def _failing_set_cache(category, data, metadata=None):
            if category == "automation_system_health":
                raise RuntimeError("simulated cache failure")
            return await original_set_cache(category, data, metadata)

        hub.set_cache = _failing_set_cache

        # Should not raise
        result = await module.generate_suggestions()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_health_cache_includes_orchestrator_status(self, hub, module):
        """Health cache reports orchestrator module presence."""
        await hub.set_cache("patterns", {"detections": []})
        await hub.set_cache("gaps", {"detections": []})

        # No orchestrator registered
        await module.generate_suggestions()
        health = await hub.get_cache("automation_system_health")
        assert health["data"]["orchestrator_loaded"] is False

        # Register a fake orchestrator
        mock_orch = MagicMock()
        mock_orch.module_id = "orchestrator"
        hub.modules["orchestrator"] = mock_orch
        hub.get_module = lambda mid: hub.modules.get(mid)

        await module.generate_suggestions()
        health = await hub.get_cache("automation_system_health")
        assert health["data"]["orchestrator_loaded"] is True


# =============================================================================
# #213 — automation_generator uses hub config for LLM model, not hardcoded
# =============================================================================


@pytest.mark.asyncio
async def test_automation_generator_uses_hub_config_for_llm_model(hub):
    """#213: automation_generator must have _get_llm_model() reading from hub config.

    After fix: AutomationGeneratorModule._get_llm_model() reads 'llm.automation_model'
    via hub.get_config_value() instead of using the hardcoded default in refine_automation.
    """
    from aria.modules.automation_generator import AutomationGeneratorModule

    module = AutomationGeneratorModule(hub)
    await module.initialize()

    # Mock get_config_value on hub so the module can read config
    hub._config_values = {"llm.automation_model": "test-model:7b"}

    async def mock_get_config_value(key, fallback=None):
        return hub._config_values.get(key, fallback)

    hub.get_config_value = mock_get_config_value

    # After fix: AutomationGeneratorModule has _get_llm_model() that uses hub config
    assert hasattr(module, "_get_llm_model"), (
        "AutomationGeneratorModule must have _get_llm_model() method after fix #213"
    )
    model = await module._get_llm_model()
    assert model == "test-model:7b", f"Expected 'test-model:7b' from hub config, got '{model}'"
