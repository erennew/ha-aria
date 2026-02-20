"""Integration tests: event → segment → features → prediction pipeline."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from aria.engine.features.feature_config import DEFAULT_FEATURE_CONFIG
from aria.engine.features.vector_builder import build_feature_vector, get_feature_names
from aria.hub.core import IntelligenceHub
from aria.modules.ml_engine import MLEngine
from aria.shared.entity_graph import EntityGraph
from aria.shared.event_store import EventStore
from aria.shared.segment_builder import SegmentBuilder

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def event_store(tmp_path):
    es = EventStore(str(tmp_path / "events.db"))
    await es.initialize()
    yield es
    await es.close()


@pytest.fixture
def entity_graph():
    return EntityGraph()


@pytest.fixture
def segment_builder(event_store, entity_graph):
    return SegmentBuilder(event_store, entity_graph)


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
        "motion": {"active_count": 1},
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


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


class TestEventToSegmentToFeatures:
    """Trace: insert events → build segment → extract features."""

    @pytest.mark.asyncio
    async def test_events_produce_segment_features(self, event_store, segment_builder):
        """Events inserted into EventStore produce non-zero segment features."""
        now = datetime.now(tz=UTC)
        start = now - timedelta(minutes=15)

        # Insert diverse events
        for i in range(10):
            await event_store.insert_event(
                timestamp=(start + timedelta(minutes=i)).isoformat(),
                entity_id=f"light.room_{i % 3}",
                domain="light",
                old_state="off",
                new_state="on",
                area_id=f"room_{i % 3}",
            )
        await event_store.insert_event(
            timestamp=(start + timedelta(minutes=5)).isoformat(),
            entity_id="binary_sensor.hallway_motion",
            domain="binary_sensor",
            old_state="off",
            new_state="on",
            attributes_json=json.dumps({"device_class": "motion"}),
        )

        segment = await segment_builder.build_segment(start.isoformat(), now.isoformat())

        assert segment["event_count"] == 11
        assert segment["light_transitions"] == 10
        assert segment["motion_events"] == 1
        assert segment["unique_entities_active"] == 4  # 3 lights + 1 motion
        assert segment["domain_entropy"] > 0
        assert segment["per_area_activity"]["room_0"] >= 1

    @pytest.mark.asyncio
    async def test_segment_feeds_into_feature_vector(self, event_store, segment_builder):
        """Segment data populates event features in the feature vector."""
        now = datetime.now(tz=UTC)
        start = now - timedelta(minutes=15)

        for i in range(5):
            await event_store.insert_event(
                timestamp=(start + timedelta(minutes=i)).isoformat(),
                entity_id="light.kitchen",
                domain="light",
                old_state="off",
                new_state="on",
            )

        segment = await segment_builder.build_segment(start.isoformat(), now.isoformat())
        snapshot = _make_snapshot()
        features = build_feature_vector(snapshot, DEFAULT_FEATURE_CONFIG, segment_data=segment)

        assert features["event_count"] == 5
        assert features["light_transitions"] == 5
        assert features["domain_entropy"] == 0.0  # single domain

    @pytest.mark.asyncio
    async def test_feature_names_cover_event_features(self):
        """get_feature_names includes all event-derived feature names."""
        names = get_feature_names(DEFAULT_FEATURE_CONFIG)
        event_features = [
            "event_count",
            "light_transitions",
            "motion_events",
            "unique_entities_active",
            "domain_entropy",
        ]
        for ef in event_features:
            assert ef in names, f"Missing event feature '{ef}' in feature names"


class TestMLEngineSegmentPipeline:
    """Trace: MLEngine._extract_features with real EventStore data."""

    @pytest.fixture
    def mock_hub(self, tmp_path, event_store, entity_graph):
        hub = Mock(spec=IntelligenceHub)
        hub.get_cache = AsyncMock(return_value=None)
        hub.get_cache_fresh = AsyncMock(return_value=None)
        hub.set_cache = AsyncMock()
        hub.logger = Mock()
        hub.hardware_profile = None
        hub.event_store = event_store
        hub.entity_graph = entity_graph
        return hub

    @pytest.fixture
    def ml_engine(self, mock_hub, tmp_path):
        models_dir = tmp_path / "models"
        training_data_dir = tmp_path / "training_data"
        models_dir.mkdir()
        training_data_dir.mkdir()
        return MLEngine(mock_hub, str(models_dir), str(training_data_dir))

    @pytest.mark.asyncio
    async def test_extract_features_with_real_events(self, ml_engine, event_store):
        """_extract_features pulls segment data from real EventStore."""
        now = datetime.now(tz=UTC)
        for i in range(8):
            await event_store.insert_event(
                timestamp=(now - timedelta(minutes=10 - i)).isoformat(),
                entity_id=f"switch.device_{i}",
                domain="switch",
                old_state="off",
                new_state="on",
            )

        snapshot = _make_snapshot()
        features = await ml_engine._extract_features(snapshot)

        assert features is not None
        assert features["event_count"] == 8
        assert features["unique_entities_active"] == 8

    @pytest.mark.asyncio
    async def test_extract_features_without_events(self, ml_engine):
        """No events = event features default to 0."""
        snapshot = _make_snapshot()
        features = await ml_engine._extract_features(snapshot)

        assert features is not None
        assert features["event_count"] == 0
        assert features["light_transitions"] == 0

    @pytest.mark.asyncio
    async def test_feature_vector_length_matches_names(self, ml_engine, event_store):
        """Feature vector keys should match _get_feature_names (for shared base)."""
        now = datetime.now(tz=UTC)
        await event_store.insert_event(
            timestamp=(now - timedelta(minutes=5)).isoformat(),
            entity_id="light.test",
            domain="light",
            old_state="off",
            new_state="on",
        )

        snapshot = _make_snapshot()
        features = await ml_engine._extract_features(snapshot)
        names = await ml_engine._get_feature_names()

        # All named features should be present in the vector (hub adds rolling
        # window and trajectory features that _extract_features also populates)
        for name in names:
            assert name in features, f"Feature '{name}' in names but not in extracted vector"


class TestPresenceConfigIntegration:
    """Trace: config weight → occupancy update → presence posterior."""

    @pytest.mark.asyncio
    async def test_occupancy_weight_affects_posterior(self):
        """Changing a sensor weight in BayesianOccupancy changes the posterior."""
        from aria.engine.analysis.occupancy import DEFAULT_PRIOR, BayesianOccupancy

        signals = [("motion", 0.95, 1.0)]

        occ_low = BayesianOccupancy()
        occ_low.update_sensor_config({"motion": {"weight": 0.1, "decay_seconds": 300}})
        low_posterior = occ_low._bayesian_fuse(DEFAULT_PRIOR, signals)

        occ_high = BayesianOccupancy()
        occ_high.update_sensor_config({"motion": {"weight": 0.9, "decay_seconds": 300}})
        high_posterior = occ_high._bayesian_fuse(DEFAULT_PRIOR, signals)

        assert high_posterior > low_posterior, (
            f"Higher motion weight should produce higher posterior: "
            f"low_weight={low_posterior:.4f}, high_weight={high_posterior:.4f}"
        )
