"""Tests for MLEngine SegmentBuilder integration."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from aria.hub.core import IntelligenceHub
from aria.modules.ml_engine import MLEngine


@pytest.fixture
def mock_hub():
    """Create mock IntelligenceHub with event_store and entity_graph."""
    hub = Mock(spec=IntelligenceHub)
    hub.get_cache = AsyncMock(return_value=None)
    hub.get_cache_fresh = AsyncMock(return_value=None)
    hub.set_cache = AsyncMock()
    hub.logger = Mock()
    hub.hardware_profile = None
    # EventStore and EntityGraph for SegmentBuilder
    hub.event_store = Mock()
    hub.entity_graph = Mock()
    return hub


@pytest.fixture
def ml_engine(mock_hub, tmp_path):
    models_dir = tmp_path / "models"
    training_data_dir = tmp_path / "training_data"
    models_dir.mkdir()
    training_data_dir.mkdir()
    return MLEngine(mock_hub, str(models_dir), str(training_data_dir))


def _make_snapshot():
    """Minimal valid snapshot for feature extraction."""
    return {
        "time_features": {
            "hour_sin": 0.5,
            "hour_cos": 0.87,
            "dow_sin": 0.0,
            "dow_cos": 1.0,
            "month_sin": 0.5,
            "month_cos": 0.87,
            "day_of_year_sin": 0.1,
            "day_of_year_cos": 0.99,
            "is_weekend": False,
            "is_holiday": False,
            "is_night": False,
            "is_work_hours": True,
            "minutes_since_sunrise": 120,
            "minutes_until_sunset": 300,
            "daylight_remaining_pct": 0.7,
        },
        "weather": {"temp_f": 72, "humidity_pct": 50, "wind_mph": 5},
        "occupancy": {"people_home": ["alice"], "device_count_home": 5},
        "lights": {"on": 3, "total_brightness": 200},
        "motion": {"active_count": 1, "sensors": {}},
        "media": {"total_active": 1},
        "power": {"total_watts": 150},
        "ev": {"TARS": {"battery_pct": 80, "is_charging": False}},
        "presence": {
            "overall_probability": 0.9,
            "occupied_room_count": 2,
            "identified_person_count": 1,
            "camera_signal_count": 0,
        },
    }


class TestSegmentBuilderInit:
    def test_segment_builder_none_initially(self, ml_engine):
        """SegmentBuilder is lazily initialized."""
        assert ml_engine._segment_builder is None

    def test_hub_event_store_accessible(self, ml_engine):
        """Hub's event_store is available for SegmentBuilder."""
        assert ml_engine.hub.event_store is not None


class TestExtractFeaturesWithSegment:
    @pytest.mark.asyncio
    async def test_extract_includes_event_features(self, ml_engine):
        """Event features should appear in extracted feature vector."""
        snapshot = _make_snapshot()

        # Mock SegmentBuilder to return known segment data
        mock_segment = {
            "event_count": 42,
            "light_transitions": 5,
            "motion_events": 8,
            "unique_entities_active": 12,
            "domain_entropy": 1.58,
            "start": "",
            "end": "",
            "per_area_activity": {},
            "per_domain_counts": {},
        }

        with patch.object(ml_engine, "_build_segment_data", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = mock_segment
            features = await ml_engine._extract_features(snapshot)

        assert features is not None
        assert features["event_count"] == 42
        assert features["light_transitions"] == 5
        assert features["motion_events"] == 8

    @pytest.mark.asyncio
    async def test_extract_without_segment_defaults_zero(self, ml_engine):
        """When _build_segment_data returns None, event features are 0."""
        snapshot = _make_snapshot()

        with patch.object(ml_engine, "_build_segment_data", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = None
            features = await ml_engine._extract_features(snapshot)

        assert features is not None
        assert features["event_count"] == 0
        assert features["light_transitions"] == 0

    @pytest.mark.asyncio
    async def test_segment_build_failure_falls_back(self, ml_engine):
        """If segment building raises, features still extract with zeros."""
        snapshot = _make_snapshot()

        with patch.object(ml_engine, "_build_segment_data", new_callable=AsyncMock) as mock_build:
            mock_build.side_effect = Exception("EventStore unavailable")
            features = await ml_engine._extract_features(snapshot)

        assert features is not None
        assert features["event_count"] == 0


class TestBuildSegmentData:
    @pytest.mark.asyncio
    async def test_builds_segment_from_event_store(self, ml_engine):
        """_build_segment_data creates SegmentBuilder and queries."""
        mock_events = [
            {
                "id": 1,
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "entity_id": "light.kitchen",
                "domain": "light",
                "old_state": "off",
                "new_state": "on",
                "device_id": None,
                "area_id": "kitchen",
                "attributes_json": None,
            }
        ]
        ml_engine.hub.event_store.query_events = AsyncMock(return_value=mock_events)

        segment = await ml_engine._build_segment_data()
        assert segment is not None
        assert segment["event_count"] == 1

    @pytest.mark.asyncio
    async def test_returns_none_when_no_event_store(self, ml_engine):
        """If hub has no event_store, returns None."""
        ml_engine.hub.event_store = None
        segment = await ml_engine._build_segment_data()
        assert segment is None

    @pytest.mark.asyncio
    async def test_lazy_segment_builder_creation(self, ml_engine):
        """SegmentBuilder is created on first use and reused."""
        ml_engine.hub.event_store.query_events = AsyncMock(return_value=[])

        assert ml_engine._segment_builder is None
        await ml_engine._build_segment_data()
        assert ml_engine._segment_builder is not None

        # Second call reuses the same instance
        builder_ref = ml_engine._segment_builder
        await ml_engine._build_segment_data()
        assert ml_engine._segment_builder is builder_ref


class TestFeatureNamesWithEvents:
    @pytest.mark.asyncio
    async def test_feature_names_include_event_features(self, ml_engine):
        """_get_feature_names includes event-derived feature names."""
        names = await ml_engine._get_feature_names()
        assert "event_count" in names
        assert "light_transitions" in names
        assert "motion_events" in names
        assert "unique_entities_active" in names
        assert "domain_entropy" in names
