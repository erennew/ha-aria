"""Tests for anomaly-gap analyzer — detects repetitive manual actions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.automation.models import DetectionResult
from aria.modules.anomaly_gap import AnomalyGapAnalyzer


def _make_event(  # noqa: PLR0913 — test helper with many optional fields
    entity_id,
    new_state="on",
    timestamp="2026-02-20T07:00:00",
    area_id=None,
    domain=None,
    old_state="off",
    context_parent_id=None,
):
    """Helper to create event dicts matching EventStore output."""
    if domain is None:
        domain = entity_id.split(".")[0]
    return {
        "entity_id": entity_id,
        "domain": domain,
        "old_state": old_state,
        "new_state": new_state,
        "timestamp": timestamp,
        "area_id": area_id,
        "device_id": None,
        "attributes_json": None,
        "context_parent_id": context_parent_id,
    }


def _make_morning_sequence(day, area="bedroom"):
    """Create a typical morning manual sequence for a given day (01-28)."""
    base = f"2026-02-{day:02d}T"
    return [
        _make_event("binary_sensor.bedroom_motion", "on", f"{base}06:50:00", area),
        _make_event("light.bedroom", "on", f"{base}06:50:30", area),
        _make_event("light.kitchen", "on", f"{base}07:05:00", "kitchen"),
    ]


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.event_store = MagicMock()
    hub.event_store.query_manual_events = AsyncMock(return_value=[])
    hub.entity_graph = MagicMock()
    hub.entity_graph.get_area.return_value = "bedroom"
    hub.cache = MagicMock()
    hub.cache.get_config_value = AsyncMock(side_effect=lambda k, d=None: d)
    return hub


@pytest.fixture
def analyzer(mock_hub):
    return AnomalyGapAnalyzer(mock_hub)


class TestFrequentSequenceMining:
    """Test the core sequence mining algorithm."""

    @pytest.mark.asyncio
    async def test_finds_repeated_pair(self, analyzer, mock_hub):
        """Two-entity sequence repeated 10+ times should be detected."""
        events = []
        for day in range(1, 16):
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T07:02:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) >= 1
        # Should find kitchen light → coffee maker pattern
        trigger_entities = {r.trigger_entity for r in results}
        assert "light.kitchen" in trigger_entities

    @pytest.mark.asyncio
    async def test_ignores_infrequent_sequence(self, analyzer, mock_hub):
        """Sequence with fewer than min_count observations is skipped."""
        events = []
        for day in range(1, 4):  # Only 3 occurrences, below default min_count=5
            events.append(_make_event("light.garage", "on", f"2026-02-{day:02d}T20:00:00", "garage"))
            events.append(_make_event("cover.garage", "open", f"2026-02-{day:02d}T20:01:00", "garage"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_respects_time_window(self, analyzer, mock_hub):
        """Events separated by more than the window are not paired."""
        events = []
        for day in range(1, 16):
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            # 2 hours later — too far apart
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T09:00:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        # Should NOT find this as a paired sequence — too far apart
        # (solo toggle results are expected and fine)
        sequence_results = [r for r in results if len(r.entity_chain) > 1]
        for r in sequence_results:
            chain_entities = {link.entity_id for link in r.entity_chain}
            assert "switch.coffee" not in chain_entities

    @pytest.mark.asyncio
    async def test_three_entity_chain(self, analyzer, mock_hub):
        """Detects chains of 3 entities."""
        events = []
        for day in range(1, 16):
            base = f"2026-02-{day:02d}T"
            events.extend(
                [
                    _make_event("binary_sensor.bedroom_motion", "on", f"{base}06:50:00", "bedroom"),
                    _make_event("light.bedroom", "on", f"{base}06:50:30", "bedroom"),
                    _make_event("light.hallway", "on", f"{base}06:51:00", "hallway"),
                ]
            )
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) >= 1
        # At least one result should have a chain of 2+ entities
        max_chain = max(len(r.entity_chain) for r in results)
        assert max_chain >= 2

    @pytest.mark.asyncio
    async def test_no_events_returns_empty(self, analyzer, mock_hub):
        """No manual events → no gaps detected."""
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=[])
        results = await analyzer.analyze_gaps()
        assert results == []


class TestDetectionResultOutput:
    """Test that results conform to DetectionResult schema."""

    @pytest.mark.asyncio
    async def test_result_is_detection_result(self, analyzer, mock_hub):
        """Each result should be a DetectionResult with source='gap'."""
        events = []
        for day in range(1, 16):
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T07:02:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) >= 1
        for r in results:
            assert isinstance(r, DetectionResult)
            assert r.source == "gap"
            assert r.observation_count >= 5
            assert r.confidence > 0
            assert r.trigger_entity != ""
            assert len(r.entity_chain) >= 1
            assert r.first_seen <= r.last_seen

    @pytest.mark.asyncio
    async def test_result_has_area_from_entity_graph(self, analyzer, mock_hub):
        """Area should be resolved from entity graph if not in event data."""
        events = []
        for day in range(1, 16):
            events.append(_make_event("light.study", "on", f"2026-02-{day:02d}T20:00:00", area_id=None))
            events.append(_make_event("light.study_lamp", "on", f"2026-02-{day:02d}T20:01:00", area_id=None))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)
        mock_hub.entity_graph.get_area.return_value = "study"

        results = await analyzer.analyze_gaps()
        if results:
            # Area should come from entity_graph fallback
            assert results[0].area_id is not None


class TestRecencyWeighting:
    """Test that recent patterns get higher recency weight."""

    @pytest.mark.asyncio
    async def test_recent_pattern_higher_weight(self, analyzer, mock_hub):
        """Pattern with last_seen today should have higher recency_weight."""
        events = []
        for day in range(1, 16):
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T07:02:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) >= 1
        for r in results:
            assert 0.0 < r.recency_weight <= 1.0


class TestConfigIntegration:
    """Test that config values drive analyzer behavior."""

    @pytest.mark.asyncio
    async def test_custom_min_count(self, mock_hub):
        """min_gap_observations config raises the detection threshold."""

        # Override config to require 20 observations
        async def config_side_effect(key, default=None):
            if key == "gap.min_observations":
                return 20
            return default

        mock_hub.cache.get_config_value = AsyncMock(side_effect=config_side_effect)
        analyzer = AnomalyGapAnalyzer(mock_hub)
        await analyzer._load_config()

        events = []
        for day in range(1, 16):  # Only 15 observations
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T07:02:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) == 0  # Below threshold

    @pytest.mark.asyncio
    async def test_custom_window_minutes(self, mock_hub):
        """window_minutes config controls pairing window."""

        async def config_side_effect(key, default=None):
            if key == "gap.window_minutes":
                return 1  # 1 minute window
            return default

        mock_hub.cache.get_config_value = AsyncMock(side_effect=config_side_effect)
        analyzer = AnomalyGapAnalyzer(mock_hub)
        await analyzer._load_config()

        events = []
        for day in range(1, 16):
            events.append(_make_event("light.kitchen", "on", f"2026-02-{day:02d}T07:00:00", "kitchen"))
            # 2 minutes later — outside 1-min window
            events.append(_make_event("switch.coffee", "on", f"2026-02-{day:02d}T07:02:00", "kitchen"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        # Coffee should NOT be paired with kitchen light (2 min > 1 min window)
        # Only check sequence results (chain > 1), solo toggles are independent
        sequence_results = [r for r in results if len(r.entity_chain) > 1]
        for r in sequence_results:
            chain_entities = {link.entity_id for link in r.entity_chain}
            assert "switch.coffee" not in chain_entities


class TestSingleEntityGaps:
    """Test detection of single entities with repetitive manual toggles."""

    @pytest.mark.asyncio
    async def test_detects_solo_manual_toggle(self, analyzer, mock_hub):
        """Single entity toggled manually at similar times should be detected."""
        events = []
        for day in range(1, 21):  # 20 days
            events.append(_make_event("light.porch", "on", f"2026-02-{day:02d}T18:30:00", "front_yard"))
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) >= 1
        # Should detect porch light as a gap
        trigger_entities = {r.trigger_entity for r in results}
        assert "light.porch" in trigger_entities

    @pytest.mark.asyncio
    async def test_solo_toggle_below_threshold_skipped(self, analyzer, mock_hub):
        """Single entity with few occurrences is not flagged."""
        events = [
            _make_event("light.porch", "on", f"2026-02-0{d}T18:30:00", "front_yard")
            for d in range(1, 4)  # Only 3
        ]
        mock_hub.event_store.query_manual_events = AsyncMock(return_value=events)

        results = await analyzer.analyze_gaps()
        assert len(results) == 0
