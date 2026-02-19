"""Known-answer tests for IntelligenceModule.

Validates that the intelligence module reads engine output files from disk,
assembles them into a structured cache payload, and produces a stable golden
snapshot.
"""

import json

import pytest

from aria.hub.constants import CACHE_INTELLIGENCE
from aria.modules.intelligence import IntelligenceModule
from tests.integration.known_answer.conftest import golden_compare

# Deterministic engine output — mimics what the ARIA engine writes to disk
MOCK_ENGINE_OUTPUT = {
    "date": "2026-02-19",
    "overall_accuracy": 84,
    "prediction_method": "blended",
    "days_of_data": 14,
    "metrics": {
        "power_watts": {"accuracy": 83, "predicted": 150.0, "actual": 145.0},
        "lights_on": {"accuracy": 65, "predicted": 20.0, "actual": 46.0},
        "devices_home": {"accuracy": 80, "predicted": 62.0, "actual": 64.0},
        "unavailable": {"accuracy": 95, "predicted": 910.0, "actual": 909.0},
        "useful_events": {"accuracy": 98, "predicted": 3700.0, "actual": 3381.0},
    },
}

# Baselines file content
MOCK_BASELINES = {
    "power_watts": {"monday": 140.0, "tuesday": 155.0},
    "lights_on": {"monday": 18.0, "tuesday": 22.0},
}

# Accuracy file content
MOCK_ACCURACY = {
    "overall": 84,
    "by_metric": {
        "power_watts": 83,
        "lights_on": 65,
    },
}

# A valid daily snapshot that passes validate_snapshot_schema
MOCK_DAILY_SNAPSHOT = {
    "power": {"total_watts": 145.0},
    "lights": {"on": 46},
    "occupancy": {"device_count_home": 64},
    "entities": {"unavailable": 909},
    "logbook_summary": {"useful_events": 3381},
}


def _create_intelligence_dir(tmp_path):
    """Build the on-disk intelligence directory structure the module expects."""
    intel_dir = tmp_path / "intelligence"
    intel_dir.mkdir()

    # Top-level JSON files
    (intel_dir / "predictions.json").write_text(json.dumps(MOCK_ENGINE_OUTPUT))
    (intel_dir / "baselines.json").write_text(json.dumps(MOCK_BASELINES))
    (intel_dir / "accuracy.json").write_text(json.dumps(MOCK_ACCURACY))

    # daily/ directory with one snapshot
    daily_dir = intel_dir / "daily"
    daily_dir.mkdir()
    (daily_dir / "2026-02-19.json").write_text(json.dumps(MOCK_DAILY_SNAPSHOT))

    # insights/ directory (empty — no insight files)
    insights_dir = intel_dir / "insights"
    insights_dir.mkdir()

    # models/ directory (empty — no ML models)
    models_dir = intel_dir / "models"
    models_dir.mkdir()

    # meta-learning/ directory (empty — no applied suggestions)
    meta_dir = intel_dir / "meta-learning"
    meta_dir.mkdir()

    return str(intel_dir)


@pytest.fixture
async def intelligence_module(hub, tmp_path, monkeypatch):
    """Create an IntelligenceModule backed by a tmp_path intelligence dir."""
    intel_dir = _create_intelligence_dir(tmp_path)
    module = IntelligenceModule(hub=hub, intelligence_dir=intel_dir)

    # Patch _read_activity_data to avoid needing activity caches
    async def mock_activity():
        return {"activity_log": None, "activity_summary": None}

    monkeypatch.setattr(module, "_read_activity_data", mock_activity)

    # Patch _parse_error_log to avoid reading real log file
    monkeypatch.setattr(module, "_parse_error_log", lambda: [])

    await module.initialize()
    return module


@pytest.mark.asyncio
async def test_reads_engine_output(intelligence_module, hub):
    """Verify intelligence module reads engine files into hub cache."""
    entry = await hub.get_cache(CACHE_INTELLIGENCE)
    assert entry is not None, "Intelligence cache should be populated after initialize()"

    data = entry["data"]

    # predictions.json should be loaded as-is
    assert data["predictions"] == MOCK_ENGINE_OUTPUT
    assert data["predictions"]["overall_accuracy"] == 84
    assert data["predictions"]["metrics"]["power_watts"]["predicted"] == 150.0

    # baselines.json should be loaded
    assert data["baselines"] == MOCK_BASELINES

    # accuracy.json should be loaded
    assert data["accuracy"] == MOCK_ACCURACY


@pytest.mark.asyncio
async def test_cache_has_expected_keys(intelligence_module, hub):
    """Verify the cached intelligence payload has the expected top-level structure."""
    entry = await hub.get_cache(CACHE_INTELLIGENCE)
    assert entry is not None

    data = entry["data"]

    # All keys that _read_intelligence_data assembles
    expected_keys = {
        "data_maturity",
        "predictions",
        "baselines",
        "trend_data",
        "intraday_trend",
        "daily_insight",
        "accuracy",
        "correlations",
        "ml_models",
        "meta_learning",
        "run_log",
        "config",
        "entity_correlations",
        "sequence_anomalies",
        "power_profiles",
        "automation_suggestions",
        "drift_status",
        "feature_selection",
        "reference_model",
        "shap_attributions",
        "autoencoder_status",
        "isolation_forest_status",
        # Added by initialize() after _read_intelligence_data
        "activity",
    }
    assert set(data.keys()) == expected_keys, (
        f"Missing: {expected_keys - set(data.keys())}, Extra: {set(data.keys()) - expected_keys}"
    )

    # data_maturity should reflect the 1 daily file we created
    maturity = data["data_maturity"]
    assert maturity["days_of_data"] == 1
    assert maturity["first_date"] == "2026-02-19"
    assert maturity["phase"] == "collecting"  # <7 days
    assert maturity["ml_active"] is False
    assert maturity["meta_learning_active"] is False

    # trend_data should have 1 entry from our daily snapshot
    assert len(data["trend_data"]) == 1
    assert data["trend_data"][0]["date"] == "2026-02-19"
    assert data["trend_data"][0]["power_watts"] == 145.0

    # ml_models defaults (no training_log.json)
    assert data["ml_models"]["count"] == 0
    assert data["ml_models"]["last_trained"] is None

    # meta_learning defaults (no applied.json)
    assert data["meta_learning"]["applied_count"] == 0

    # config should have defaults
    assert data["config"]["anomaly_threshold"] == 2.0
    assert "ml_weight_schedule" in data["config"]


@pytest.mark.asyncio
async def test_golden_snapshot(intelligence_module, hub, update_golden):
    """Golden snapshot of intelligence cache content."""
    entry = await hub.get_cache(CACHE_INTELLIGENCE)
    assert entry is not None

    data = entry["data"]

    # Build a deterministic snapshot — exclude run_log timestamps (mtime-based)
    snapshot = {k: v for k, v in sorted(data.items()) if k != "run_log"}

    # run_log entries have mtime-based timestamps — normalize them
    run_log = data.get("run_log", [])
    snapshot["run_log"] = [{"type": r["type"], "status": r["status"]} for r in run_log]

    golden_compare(snapshot, "intelligence_cache", update=update_golden)

    # Structural assertion independent of golden file
    assert "predictions" in snapshot
    assert "baselines" in snapshot
    assert "data_maturity" in snapshot
