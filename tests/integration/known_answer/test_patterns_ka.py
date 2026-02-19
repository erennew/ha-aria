"""Known-answer tests for PatternRecognition module.

Validates pattern detection, hub cache storage, and golden snapshot stability
against hand-crafted logbook data with clear recurring routines.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aria.modules.patterns import PatternRecognition
from tests.integration.known_answer.conftest import FIXTURES_DIR, golden_compare


def _write_logbook_files(log_dir: Path) -> None:
    """Write fixture logbook files into log_dir as individual date files.

    PatternRecognition._extract_sequences reads files matching ``2026-*.json``
    from ``log_dir``.  Each key in the fixture is a date string mapped to
    a list of logbook events.
    """
    fixture_path = FIXTURES_DIR / "logbook_patterns.json"
    fixture_data = json.loads(fixture_path.read_text())

    for date_str, events in fixture_data.items():
        file_path = log_dir / f"{date_str}.json"
        file_path.write_text(json.dumps(events, indent=2))


@pytest.fixture
async def patterns_module(hub, tmp_path):
    """Create a PatternRecognition module backed by fixture logbook data.

    Uses lowered thresholds so the hand-crafted 4-day fixture reliably
    triggers pattern detection.  The Ollama LLM call is mocked to return
    a fixed label.
    """
    log_dir = tmp_path / "ha-logs"
    log_dir.mkdir()
    _write_logbook_files(log_dir)

    module = PatternRecognition(
        hub=hub,
        log_dir=log_dir,
        min_pattern_frequency=2,
        min_support=0.5,
        min_confidence=0.5,
    )

    return module


def _mock_ollama_generate(**kwargs):
    """Deterministic stand-in for ``ollama.generate``."""

    class _Response:
        response = "Morning routine"

    return _Response()


@pytest.mark.asyncio
async def test_detects_recurring_patterns(patterns_module):
    """Pattern detection should find >= 1 pattern from the kitchen morning routine."""
    with patch("aria.modules.patterns.ollama.generate", side_effect=_mock_ollama_generate):
        patterns = await patterns_module.detect_patterns()

    assert len(patterns) >= 1, f"Expected at least 1 pattern, got {len(patterns)}"

    # At least one pattern should be in the kitchen area
    areas = {p["area"] for p in patterns}
    assert "kitchen" in areas, f"Expected 'kitchen' area in patterns, got areas: {areas}"


@pytest.mark.asyncio
async def test_patterns_cached(patterns_module, hub):
    """Detected patterns should be stored in hub cache under 'patterns' key."""
    with patch("aria.modules.patterns.ollama.generate", side_effect=_mock_ollama_generate):
        patterns = await patterns_module.detect_patterns()

    cache_entry = await hub.get_cache("patterns")
    assert cache_entry is not None, "patterns cache entry should exist after detect_patterns()"

    data = cache_entry["data"]
    assert "patterns" in data
    assert "pattern_count" in data
    assert "areas_analyzed" in data
    assert data["pattern_count"] == len(patterns)
    assert data["pattern_count"] >= 1


@pytest.mark.asyncio
async def test_golden_snapshot(patterns_module, hub, update_golden):
    """Golden snapshot of normalized pattern output (timestamps removed, entities sorted, confidence rounded)."""
    with patch("aria.modules.patterns.ollama.generate", side_effect=_mock_ollama_generate):
        patterns = await patterns_module.detect_patterns()

    # Normalize patterns for deterministic comparison
    normalized = []
    for p in sorted(patterns, key=lambda x: (x["area"], x.get("typical_time", ""))):
        normalized.append(
            {
                "pattern_id": p["pattern_id"],
                "area": p["area"],
                "typical_time": p["typical_time"],
                "frequency": p["frequency"],
                "confidence": round(p["confidence"], 2),
                "associated_signals": sorted(p.get("associated_signals", [])),
                "llm_description": p.get("llm_description", ""),
            }
        )

    snapshot = {"patterns": normalized, "pattern_count": len(normalized)}
    golden_compare(snapshot, "patterns_detection", update=update_golden)

    # Verify snapshot is non-empty
    assert len(normalized) >= 1, "Golden snapshot should contain at least 1 pattern"
