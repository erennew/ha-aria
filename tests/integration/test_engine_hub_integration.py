"""Integration tests: verify engine and hub can interoperate within the aria namespace."""

import json
from unittest.mock import MagicMock

from aria.engine.schema import REQUIRED_NESTED_KEYS, validate_snapshot_schema
from aria.modules.intelligence import METRIC_PATHS

# ---------------------------------------------------------------------------
# Contract tests: engine JSON schema ↔ hub reader (RISK-01)
# ---------------------------------------------------------------------------


def _minimal_valid_snapshot() -> dict:
    """Build a minimal snapshot that satisfies every required nested key."""
    return {
        "power": {"total_watts": 450.0},
        "occupancy": {"device_count_home": 2},
        "lights": {"on": 5},
        "logbook_summary": {"useful_events": 12},
        "entities": {"unavailable": 1},
    }


def test_snapshot_schema_round_trip():
    """A minimal valid snapshot should pass validate_snapshot_schema with no errors."""
    snapshot = _minimal_valid_snapshot()
    errors = validate_snapshot_schema(snapshot)
    assert errors == [], f"Expected no validation errors, got: {errors}"


def test_required_keys_match_hub_reader():
    """Every snapshot key accessed by METRIC_PATHS must be covered by REQUIRED_NESTED_KEYS.

    METRIC_PATHS uses d.get("section", {}).get("nested_key"). Each (section, nested_key)
    pair it accesses must appear in REQUIRED_NESTED_KEYS so the schema validator enforces
    those keys are present whenever the section exists.
    """

    # Extract (section, nested_key) pairs from METRIC_PATHS lambdas by running
    # them against a probe object that records attribute access.
    class _Probe(dict):
        def __init__(self, section, results):
            super().__init__()
            self._section = section
            self._results = results

        def get(self, key, default=None):
            if self._section is not None:
                self._results.append((self._section, key))
                return None
            # First-level get — return a probe for the section
            child = _Probe(key, self._results)
            return child

    accessed_pairs = []
    probe = _Probe(None, accessed_pairs)
    for extractor in METRIC_PATHS.values():
        extractor(probe)

    # Every (section, nested_key) the hub reader touches must be covered by schema
    for section, nested_key in accessed_pairs:
        assert section in REQUIRED_NESTED_KEYS, (
            f"METRIC_PATHS accesses section '{section}' but it is not in REQUIRED_NESTED_KEYS. "
            "Add it so schema validation enforces its structure."
        )
        assert nested_key in REQUIRED_NESTED_KEYS[section], (
            f"METRIC_PATHS accesses '{section}.{nested_key}' but '{nested_key}' is not in "
            f"REQUIRED_NESTED_KEYS['{section}']. Add it to close the contract gap."
        )


def test_schema_rejects_missing_required_keys():
    """A snapshot with a present-but-incomplete section must produce validation errors."""
    # Section present but missing its required nested key
    incomplete = {
        "power": {},  # missing "total_watts"
        "occupancy": {"device_count_home": 1},
        "lights": {"on": 3},
        "logbook_summary": {"useful_events": 5},
        "entities": {"unavailable": 0},
    }
    errors = validate_snapshot_schema(incomplete)
    assert len(errors) > 0, "Expected validation errors for incomplete 'power' section"
    assert any("power" in e for e in errors), f"Expected error mentioning 'power', got: {errors}"


def test_engine_output_consumable_by_hub(tmp_path):
    """A snapshot written by the engine should be readable by the hub intelligence module.

    Creates a realistic daily snapshot on disk, instantiates IntelligenceModule with
    a mocked hub, calls _extract_trend_data(), and verifies it produces valid cache entries.
    """
    from aria.modules.intelligence import IntelligenceModule

    # Write a valid daily snapshot to a temp directory
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir(parents=True)
    snapshot = _minimal_valid_snapshot()
    snapshot_file = daily_dir / "2026-02-18.json"
    snapshot_file.write_text(json.dumps(snapshot))

    # Build a minimal mock hub (IntelligenceModule only reads hub at cache-write time)
    mock_hub = MagicMock()
    mock_hub.logger = MagicMock()

    module = IntelligenceModule(hub=mock_hub, intelligence_dir=str(tmp_path))

    # _extract_trend_data reads the daily files, validates schema, extracts metrics
    trend = module._extract_trend_data([snapshot_file])

    # Should produce exactly one trend entry (one file, valid schema)
    assert len(trend) == 1, f"Expected 1 trend entry from valid snapshot, got {len(trend)}"

    entry = trend[0]
    assert entry["date"] == "2026-02-18", f"Expected date '2026-02-18', got {entry.get('date')}"

    # All METRIC_PATHS keys that have values in the snapshot should appear in the entry
    assert entry.get("power_watts") == 450.0
    assert entry.get("lights_on") == 5
    assert entry.get("devices_home") == 2
    assert entry.get("unavailable") == 1
    assert entry.get("useful_events") == 12


def test_engine_imports_accessible_from_hub():
    """Verify hub code can import engine modules."""
    from aria.engine.analysis.entity_correlations import summarize_entity_correlations
    from aria.engine.analysis.sequence_anomalies import MarkovChainDetector
    from aria.engine.config import AppConfig
    from aria.engine.storage.data_store import DataStore

    assert AppConfig is not None
    assert DataStore is not None
    assert summarize_entity_correlations is not None
    assert MarkovChainDetector is not None


def test_hub_imports_accessible():
    """Verify hub core can be imported."""
    from aria.hub.cache import CacheManager
    from aria.hub.constants import CACHE_INTELLIGENCE
    from aria.hub.core import IntelligenceHub, Module

    assert IntelligenceHub is not None
    assert Module is not None
    assert CacheManager is not None
    assert isinstance(CACHE_INTELLIGENCE, str)


def test_module_imports_accessible():
    """Verify all hub modules can be imported."""
    from aria.modules.activity_monitor import ActivityMonitor
    from aria.modules.discovery import DiscoveryModule
    from aria.modules.intelligence import IntelligenceModule
    from aria.modules.ml_engine import MLEngine
    from aria.modules.orchestrator import OrchestratorModule
    from aria.modules.patterns import PatternRecognition
    from aria.modules.shadow_engine import ShadowEngine

    assert IntelligenceModule is not None
    assert DiscoveryModule is not None
    assert ShadowEngine is not None
    assert ActivityMonitor is not None
    assert MLEngine is not None
    assert PatternRecognition is not None
    assert OrchestratorModule is not None


def test_engine_and_hub_share_namespace():
    """Verify engine and hub live under the same aria package."""
    import aria

    assert hasattr(aria, "__version__")

    import aria.engine
    import aria.hub
    import aria.modules

    # Both are subpackages of the same top-level
    assert aria.engine.__name__.startswith("aria.")
    assert aria.hub.__name__.startswith("aria.")
    assert aria.modules.__name__.startswith("aria.")


def test_cli_entry_point_importable():
    """Verify the CLI entry point can be imported."""
    from aria.cli import main

    assert callable(main)
