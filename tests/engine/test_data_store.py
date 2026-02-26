"""Tests for DataStore corrupt JSON guards.

Verifies that every load_* method on DataStore catches json.JSONDecodeError
and returns the correct typed empty default instead of propagating the
exception (Cluster A — Silent Failures audit fix).
"""

import json
from pathlib import Path

import pytest

from aria.engine.config import PathConfig
from aria.engine.storage.data_store import DataStore


@pytest.fixture
def store_with_tmp(tmp_path):
    """Return a (store, tmp_path) pair backed by a fresh temp directory."""
    paths = PathConfig(data_dir=tmp_path / "intelligence", logbook_path=tmp_path / "logbook.json")
    paths.ensure_dirs()
    return DataStore(paths), paths


def _write_corrupt(path: Path) -> None:
    """Write a file that is not valid JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt json !!!")


# ---------------------------------------------------------------------------
# load_snapshot
# ---------------------------------------------------------------------------


def test_load_snapshot_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    corrupt_path = paths.daily_dir / "2026-01-01.json"
    _write_corrupt(corrupt_path)

    result = store.load_snapshot("2026-01-01")
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_snapshot_missing_returns_none(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_snapshot("1999-01-01") is None


# ---------------------------------------------------------------------------
# load_baselines
# ---------------------------------------------------------------------------


def test_load_baselines_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.baselines_path)

    result = store.load_baselines()
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_baselines_missing_returns_empty_dict(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_baselines() == {}


# ---------------------------------------------------------------------------
# load_predictions
# ---------------------------------------------------------------------------


def test_load_predictions_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.predictions_path)

    result = store.load_predictions()
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_predictions_missing_returns_empty_dict(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_predictions() == {}


# ---------------------------------------------------------------------------
# load_correlations
# ---------------------------------------------------------------------------


def test_load_correlations_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.correlations_path)

    result = store.load_correlations()
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_correlations_missing_returns_empty_dict(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_correlations() == {}


# ---------------------------------------------------------------------------
# load_entity_correlations
# ---------------------------------------------------------------------------


def test_load_entity_correlations_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    corrupt_path = paths.data_dir / "entity_correlations.json"
    _write_corrupt(corrupt_path)

    result = store.load_entity_correlations()
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_entity_correlations_missing_returns_empty_dict(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_entity_correlations() == {}


# ---------------------------------------------------------------------------
# load_accuracy_history
# ---------------------------------------------------------------------------


def test_load_accuracy_history_corrupt_returns_default(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.accuracy_path)

    result = store.load_accuracy_history()
    assert result == {"scores": []}
    assert "corrupt JSON" in caplog.text


def test_load_accuracy_history_missing_returns_default(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_accuracy_history() == {"scores": []}


# ---------------------------------------------------------------------------
# load_feature_config
# ---------------------------------------------------------------------------


def test_load_feature_config_corrupt_returns_empty_dict(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.feature_config_path)

    result = store.load_feature_config()
    assert result == {}
    assert "corrupt JSON" in caplog.text


def test_load_feature_config_missing_returns_none(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_feature_config() is None


# ---------------------------------------------------------------------------
# load_applied_suggestions
# ---------------------------------------------------------------------------


def test_load_applied_suggestions_corrupt_returns_default(store_with_tmp, caplog):
    store, paths = store_with_tmp
    # meta_dir must exist for the path to be relevant
    paths.meta_dir.mkdir(parents=True, exist_ok=True)
    corrupt_path = paths.meta_dir / "applied.json"
    _write_corrupt(corrupt_path)

    result = store.load_applied_suggestions()
    assert result == {"applied": [], "total_applied": 0}
    assert "corrupt JSON" in caplog.text


def test_load_applied_suggestions_missing_returns_default(store_with_tmp):
    store, _ = store_with_tmp
    result = store.load_applied_suggestions()
    assert result == {"applied": [], "total_applied": 0}


# ---------------------------------------------------------------------------
# load_sequence_model
# ---------------------------------------------------------------------------


def test_load_sequence_model_corrupt_returns_none(store_with_tmp, caplog):
    store, paths = store_with_tmp
    _write_corrupt(paths.sequence_model_path)

    result = store.load_sequence_model()
    assert result is None
    assert "corrupt JSON" in caplog.text


def test_load_sequence_model_missing_returns_none(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_sequence_model() is None


# ---------------------------------------------------------------------------
# load_sequence_anomalies
# ---------------------------------------------------------------------------


def test_load_sequence_anomalies_corrupt_returns_none(store_with_tmp, caplog):
    store, paths = store_with_tmp
    corrupt_path = paths.data_dir / "sequence_anomalies.json"
    _write_corrupt(corrupt_path)

    result = store.load_sequence_anomalies()
    assert result is None
    assert "corrupt JSON" in caplog.text


def test_load_sequence_anomalies_missing_returns_none(store_with_tmp):
    store, _ = store_with_tmp
    assert store.load_sequence_anomalies() is None


# ---------------------------------------------------------------------------
# Happy-path smoke: valid JSON is still returned correctly
# ---------------------------------------------------------------------------


def test_load_baselines_valid_json_returned(store_with_tmp):
    store, paths = store_with_tmp
    data = {"entity.light": {"mean": 0.5}}
    paths.baselines_path.write_text(json.dumps(data))

    result = store.load_baselines()
    assert result == data


def test_load_predictions_valid_json_returned(store_with_tmp):
    store, paths = store_with_tmp
    data = {"metric": 42.0}
    paths.predictions_path.write_text(json.dumps(data))

    result = store.load_predictions()
    assert result == data
