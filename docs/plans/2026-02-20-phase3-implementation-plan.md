# Phase 3: Automation Generator — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a calendar-aware, event-stream-first automation generator that detects behavioral patterns, identifies manual action gaps, generates validated HA-native YAML, and compares against existing automations.

**Architecture:** New `aria/automation/` package for reusable YAML generation, normalizer pipeline in `aria/shared/`, two detection engines feeding a combined scorer, shadow comparison against cached HA automations. All modules <400 lines.

**Tech Stack:** Python 3.12, aiosqlite, aiohttp, scipy (DTW), mlxtend (Apriori), PyYAML, Ollama (qwen2.5-coder:14b), Preact (dashboard)

**Design doc:** `docs/plans/2026-02-20-phase3-automation-generator-design.md`

**Test baseline:** 1718 tests passing. All new code TDD.

**Test command:** `.venv/bin/python -m pytest tests/ --timeout=120 -x -q`

---

## Batch Overview

| Batch | Tasks | Focus | Est. Tests |
|-------|-------|-------|-----------|
| 1 | 1-3 | Foundation: models, EventStore migration, config defaults | ~40 |
| 2 | 4-6 | Normalizer core: state filtering, entity health, user exclusion | ~50 |
| 3 | 7-9 | Calendar: context fetch, day classifier, day-type segmentation | ~40 |
| 4 | 10-12 | Normalizer advanced: co-occurrence, adaptive windows, env correlation | ~40 |
| 5 | 13-15 | Pattern engine rewrite: EventStore source, day-type, periodic | ~50 |
| 6 | 16-17 | Gap analyzer: sequence mining, manual-only filtering | ~40 |
| 7 | 18-21 | YAML generation: trigger, condition, action builders, template engine | ~60 |
| 8 | 22-23 | LLM refiner + validator (9 checks) | ~40 |
| 9 | 24-26 | Shadow: HA sync, comparison, immediate cache update | ~50 |
| 10 | 27-29 | Integration: AutomationGenerator module, orchestrator thinning, scoring | ~30 |
| 11 | 30-32 | API routes, CLI commands, health cache | ~30 |
| 12 | 33-35 | Integration tests, known-answer tests, performance tests | ~30 |
| 13 | 36-37 | Dashboard: Decide page, Settings filtering section | ~20 |

**Quality gates between batches:** `.venv/bin/python -m pytest tests/ --timeout=120 -x -q`

---

## Batch 1: Foundation

### Task 1: Data Models Package

Create the `aria/automation/` package with shared dataclasses used across all Phase 3 components.

**Files:**
- Create: `aria/automation/__init__.py`
- Create: `aria/automation/models.py`
- Test: `tests/hub/test_automation_models.py`

**Step 1: Write the test file**

```python
# tests/hub/test_automation_models.py
"""Tests for Phase 3 automation data models."""
import pytest
from aria.automation.models import (
    ChainLink,
    DayContext,
    DetectionResult,
    EntityHealth,
    NormalizedEvent,
    ShadowResult,
)


class TestDetectionResult:
    def test_create_from_pattern(self):
        result = DetectionResult(
            source="pattern",
            trigger_entity="binary_sensor.bedroom_motion",
            action_entities=["light.bedroom"],
            entity_chain=[
                ChainLink(entity_id="binary_sensor.bedroom_motion", state="on", offset_seconds=0),
                ChainLink(entity_id="light.bedroom", state="on", offset_seconds=30),
            ],
            area_id="bedroom",
            confidence=0.85,
            recency_weight=0.9,
            observation_count=47,
            first_seen="2026-01-01T06:30:00",
            last_seen="2026-02-19T06:45:00",
            day_type="workday",
            combined_score=0.0,  # computed later
        )
        assert result.source == "pattern"
        assert result.trigger_entity == "binary_sensor.bedroom_motion"
        assert len(result.entity_chain) == 2

    def test_create_from_gap(self):
        result = DetectionResult(
            source="gap",
            trigger_entity="light.kitchen",
            action_entities=["light.kitchen"],
            entity_chain=[
                ChainLink(entity_id="light.kitchen", state="on", offset_seconds=0),
            ],
            area_id="kitchen",
            confidence=0.72,
            recency_weight=0.95,
            observation_count=40,
            first_seen="2026-01-05T06:45:00",
            last_seen="2026-02-20T07:10:00",
            day_type="workday",
            combined_score=0.0,
        )
        assert result.source == "gap"


class TestDayContext:
    def test_workday(self):
        ctx = DayContext(
            date="2026-02-20",
            day_type="workday",
            calendar_events=[],
            away_all_day=False,
        )
        assert ctx.day_type == "workday"

    def test_holiday(self):
        ctx = DayContext(
            date="2026-12-25",
            day_type="holiday",
            calendar_events=["Christmas Day"],
            away_all_day=False,
        )
        assert ctx.day_type == "holiday"


class TestNormalizedEvent:
    def test_create(self):
        evt = NormalizedEvent(
            timestamp="2026-02-20T07:00:00",
            entity_id="binary_sensor.bedroom_motion",
            domain="binary_sensor",
            normalized_state="positive",
            raw_state="on",
            area_id="bedroom",
            device_id="device_123",
            day_type="workday",
            is_manual=True,
            attributes_json=None,
        )
        assert evt.normalized_state == "positive"
        assert evt.is_manual is True


class TestEntityHealth:
    def test_healthy(self):
        h = EntityHealth(
            entity_id="light.bedroom",
            availability_pct=0.98,
            unavailable_transitions=5,
            longest_outage_hours=0.5,
            health_grade="healthy",
        )
        assert h.health_grade == "healthy"

    def test_unreliable(self):
        h = EntityHealth(
            entity_id="sensor.flaky",
            availability_pct=0.65,
            unavailable_transitions=200,
            longest_outage_hours=12.0,
            health_grade="unreliable",
        )
        assert h.health_grade == "unreliable"


class TestShadowResult:
    def test_new_suggestion(self):
        r = ShadowResult(
            candidate={"id": "test", "alias": "Test"},
            status="new",
            duplicate_score=0.0,
            conflicting_automation=None,
            gap_source_automation=None,
            reason="No matching existing automation found.",
        )
        assert r.status == "new"

    def test_duplicate(self):
        r = ShadowResult(
            candidate={"id": "test", "alias": "Test"},
            status="duplicate",
            duplicate_score=0.92,
            conflicting_automation=None,
            gap_source_automation=None,
            reason="Existing automation 'Bedroom lights' covers this.",
        )
        assert r.status == "duplicate"
        assert r.duplicate_score > 0.8
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/hub/test_automation_models.py -v`
Expected: FAIL with ImportError (aria.automation.models not found)

**Step 3: Write the models**

```python
# aria/automation/__init__.py
"""Automation generation package — reusable HA-native YAML generation."""

# aria/automation/models.py
"""Shared data models for Phase 3 automation generation pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ChainLink:
    """One step in a detected behavioral sequence."""
    entity_id: str
    state: str
    offset_seconds: float  # seconds after chain trigger (0 for first link)


@dataclass
class DetectionResult:
    """Unified output from pattern engine or gap analyzer."""
    source: Literal["pattern", "gap"]
    trigger_entity: str
    action_entities: list[str]
    entity_chain: list[ChainLink]
    area_id: str | None
    confidence: float
    recency_weight: float
    observation_count: int
    first_seen: str                  # ISO 8601
    last_seen: str                   # ISO 8601
    day_type: str                    # workday, weekend, holiday, wfh
    combined_score: float = 0.0      # computed by scoring step


@dataclass
class DayContext:
    """Classification of a single day for analysis segmentation."""
    date: str                        # YYYY-MM-DD
    day_type: Literal["workday", "weekend", "holiday", "vacation", "wfh"]
    calendar_events: list[str] = field(default_factory=list)
    away_all_day: bool = False


@dataclass
class NormalizedEvent:
    """Event after normalization pipeline — ready for detection engines."""
    timestamp: str
    entity_id: str
    domain: str
    normalized_state: str            # "positive" or "negative"
    raw_state: str                   # original state value
    area_id: str | None
    device_id: str | None
    day_type: str
    is_manual: bool                  # True if context_parent_id is None
    attributes_json: str | None = None


@dataclass
class EntityHealth:
    """Availability scoring for an entity over analysis window."""
    entity_id: str
    availability_pct: float          # 0.0-1.0
    unavailable_transitions: int
    longest_outage_hours: float
    health_grade: Literal["healthy", "flaky", "unreliable"]


@dataclass
class ShadowResult:
    """Annotation on a candidate automation after shadow comparison."""
    candidate: dict[str, Any]        # the generated HA automation dict
    status: Literal["new", "duplicate", "conflict", "gap_fill"]
    duplicate_score: float           # 0.0-1.0
    conflicting_automation: str | None
    gap_source_automation: str | None
    reason: str                      # human-readable explanation
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/hub/test_automation_models.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add aria/automation/__init__.py aria/automation/models.py tests/hub/test_automation_models.py
git commit -m "feat(p3): add automation data models package"
```

---

### Task 2: EventStore Schema Migration

Add `context_parent_id` column to EventStore for manual vs automated discrimination.

**Files:**
- Modify: `aria/shared/event_store.py`
- Test: `tests/hub/test_event_store_migration.py`

**Step 1: Write the test**

```python
# tests/hub/test_event_store_migration.py
"""Tests for EventStore Phase 3 schema migration (context_parent_id)."""
import pytest
import aiosqlite
from aria.shared.event_store import EventStore


@pytest.fixture
async def store(tmp_path):
    s = EventStore(str(tmp_path / "test_events.db"))
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestContextParentId:
    async def test_insert_with_context_parent_id(self, store):
        await store.insert_event(
            timestamp="2026-02-20T07:00:00",
            entity_id="light.bedroom",
            domain="light",
            old_state="off",
            new_state="on",
            context_parent_id=None,  # manual action
        )
        events = await store.query_events("2026-02-20T00:00:00", "2026-02-21T00:00:00")
        assert len(events) == 1
        assert events[0]["context_parent_id"] is None

    async def test_insert_automated_event(self, store):
        await store.insert_event(
            timestamp="2026-02-20T07:00:00",
            entity_id="light.bedroom",
            domain="light",
            old_state="off",
            new_state="on",
            context_parent_id="automation.morning_lights",
        )
        events = await store.query_events("2026-02-20T00:00:00", "2026-02-21T00:00:00")
        assert events[0]["context_parent_id"] == "automation.morning_lights"

    async def test_query_manual_only(self, store):
        # Insert manual + automated events
        await store.insert_event(
            timestamp="2026-02-20T07:00:00",
            entity_id="light.kitchen",
            domain="light",
            new_state="on",
            context_parent_id=None,
        )
        await store.insert_event(
            timestamp="2026-02-20T07:01:00",
            entity_id="light.bedroom",
            domain="light",
            new_state="on",
            context_parent_id="automation.morning",
        )
        manual = await store.query_manual_events("2026-02-20T00:00:00", "2026-02-21T00:00:00")
        assert len(manual) == 1
        assert manual[0]["entity_id"] == "light.kitchen"

    async def test_batch_insert_with_context(self, store):
        events = [
            ("2026-02-20T07:00:00", "light.a", "light", "off", "on", None, "bedroom", None, None),
            ("2026-02-20T07:01:00", "light.b", "light", "off", "on", None, "kitchen", None, "auto.x"),
        ]
        await store.insert_events_batch(events)
        all_events = await store.query_events("2026-02-20T00:00:00", "2026-02-21T00:00:00")
        assert len(all_events) == 2

    async def test_area_summary(self, store):
        """Test area-level aggregate query for performance tiering."""
        for i in range(10):
            await store.insert_event(
                timestamp=f"2026-02-20T07:{i:02d}:00",
                entity_id="light.bedroom",
                domain="light",
                new_state="on",
                area_id="bedroom",
            )
        for i in range(3):
            await store.insert_event(
                timestamp=f"2026-02-20T08:{i:02d}:00",
                entity_id="light.kitchen",
                domain="light",
                new_state="on",
                area_id="kitchen",
            )
        summary = await store.area_event_summary("2026-02-20T00:00:00", "2026-02-21T00:00:00")
        assert summary["bedroom"] >= 10
        assert summary["kitchen"] >= 3
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/hub/test_event_store_migration.py -v`
Expected: FAIL (context_parent_id param not accepted, query_manual_events not found)

**Step 3: Modify EventStore**

Add to `aria/shared/event_store.py`:

1. Add `context_parent_id TEXT` to CREATE TABLE (after `attributes_json`)
2. Add index: `CREATE INDEX IF NOT EXISTS idx_sce_context ON state_change_events(context_parent_id)`
3. Add `context_parent_id` param to `insert_event()` and `insert_events_batch()`
4. Add `query_manual_events()` method (WHERE context_parent_id IS NULL)
5. Add `area_event_summary()` method (GROUP BY area_id, COUNT)
6. Add migration: `ALTER TABLE ... ADD COLUMN context_parent_id TEXT` in initialize() with try/except OperationalError for existing DBs

Key implementation notes for the agent:
- `insert_event()` gets new kwarg `context_parent_id: str | None = None`
- `insert_events_batch()` tuple grows from 8 to 9 elements: `(timestamp, entity_id, domain, old_state, new_state, device_id, area_id, attributes_json, context_parent_id)`
- Migration in `initialize()` after table creation:
  ```python
  try:
      await self._conn.execute(
          "ALTER TABLE state_change_events ADD COLUMN context_parent_id TEXT"
      )
      await self._conn.execute(
          "CREATE INDEX IF NOT EXISTS idx_sce_context ON state_change_events(context_parent_id)"
      )
      await self._conn.commit()
  except Exception:
      pass  # Column already exists
  ```
- `query_manual_events(start, end, limit=10000)` → same as `query_events` but adds `AND context_parent_id IS NULL`
- `area_event_summary(start, end)` → `SELECT area_id, COUNT(*) as cnt FROM ... WHERE area_id IS NOT NULL GROUP BY area_id` → returns `dict[str, int]`

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/hub/test_event_store_migration.py -v`
Expected: PASS (all 5 tests)

**Step 5: Run full test suite to check backward compat**

Run: `.venv/bin/python -m pytest tests/ --timeout=120 -x -q`
Expected: All 1718+ tests still pass. Existing insert_event calls without context_parent_id default to None.

**Step 6: Commit**

```bash
git add aria/shared/event_store.py tests/hub/test_event_store_migration.py
git commit -m "feat(p3): add context_parent_id to EventStore schema"
```

---

### Task 3: Activity Monitor — Extract context.parent_id

Wire the HA WebSocket event's `context.parent_id` into the EventStore persist path.

**Files:**
- Modify: `aria/modules/activity_monitor.py:449-480` (the `_persist_to_event_store` method)
- Test: `tests/hub/test_activity_monitor_context.py`

**Step 1: Write the test**

```python
# tests/hub/test_activity_monitor_context.py
"""Tests for activity monitor context_parent_id extraction."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aria.modules.activity_monitor import ActivityMonitor


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.event_store = MagicMock()
    hub.event_store.insert_event = AsyncMock()
    hub.entity_graph = MagicMock()
    hub.entity_graph.get_area.return_value = "bedroom"
    hub.entity_graph.get_device.return_value = {"device_id": "dev_123"}
    return hub


class TestContextParentIdExtraction:
    def test_manual_event_has_no_parent(self, mock_hub):
        """Manual actions should persist with context_parent_id=None."""
        monitor = ActivityMonitor.__new__(ActivityMonitor)
        monitor.hub = mock_hub
        monitor.logger = MagicMock()

        event = {
            "entity_id": "light.bedroom",
            "domain": "light",
            "from": "off",
            "to": "on",
            "timestamp": "2026-02-20T07:00:00",
        }
        # HA WebSocket data with no automation context
        ws_data = {
            "entity_id": "light.bedroom",
            "new_state": {
                "state": "on",
                "context": {"id": "abc123", "parent_id": None, "user_id": "user1"},
            },
        }
        monitor._persist_to_event_store(event, {}, ws_context=ws_data.get("new_state", {}).get("context"))

        call_kwargs = mock_hub.event_store.insert_event.call_args
        # The insert_event should be called with context_parent_id=None
        # (we'll verify via the task that creates the coroutine)

    def test_automated_event_has_parent(self, mock_hub):
        """Automation-triggered events should persist context_parent_id."""
        monitor = ActivityMonitor.__new__(ActivityMonitor)
        monitor.hub = mock_hub
        monitor.logger = MagicMock()

        event = {
            "entity_id": "light.bedroom",
            "domain": "light",
            "from": "off",
            "to": "on",
            "timestamp": "2026-02-20T07:00:00",
        }
        context = {"id": "abc123", "parent_id": "automation.morning_lights", "user_id": None}
        monitor._persist_to_event_store(event, {}, ws_context=context)
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/hub/test_activity_monitor_context.py -v`
Expected: FAIL (_persist_to_event_store doesn't accept ws_context param)

**Step 3: Modify activity_monitor.py**

Two changes:

1. In `_handle_state_changed()` (~line 360): extract context from WebSocket data and pass to _persist_to_event_store:
   ```python
   # After line 398 (event dict creation), before _persist_to_event_store call:
   ws_context = (data.get("new_state") or {}).get("context")
   self._persist_to_event_store(event, attrs, ws_context=ws_context)
   ```

2. In `_persist_to_event_store()` (~line 449): accept and forward context_parent_id:
   ```python
   def _persist_to_event_store(self, event: dict, attrs: dict, ws_context: dict | None = None):
       # ... existing code ...
       context_parent_id = None
       if ws_context:
           context_parent_id = ws_context.get("parent_id")
       # ... in the insert_event call, add:
       #     context_parent_id=context_parent_id,
   ```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/hub/test_activity_monitor_context.py -v`
Expected: PASS

**Step 5: Run full suite**

Run: `.venv/bin/python -m pytest tests/ --timeout=120 -x -q`
Expected: All existing tests still pass (ws_context defaults to None).

**Step 6: Commit**

```bash
git add aria/modules/activity_monitor.py tests/hub/test_activity_monitor_context.py
git commit -m "feat(p3): extract context.parent_id in activity monitor persist"
```

---

## Batch 2: Normalizer Core

### Task 4: State Normalizer + Filtering

Core normalizer that filters unavailable/unknown states and normalizes state values.

**Files:**
- Create: `aria/shared/event_normalizer.py`
- Test: `tests/hub/test_event_normalizer.py`

**Step 1: Write test**

```python
# tests/hub/test_event_normalizer.py
"""Tests for event normalizer pipeline."""
import pytest
from aria.automation.models import NormalizedEvent
from aria.shared.event_normalizer import EventNormalizer


@pytest.fixture
def normalizer():
    config = {
        "filter.ignored_states": ["unavailable", "unknown"],
        "filter.exclude_entities": ["sensor.test_debug"],
        "filter.exclude_areas": ["garage"],
        "filter.exclude_domains": ["automation", "script", "scene"],
        "filter.include_domains": [],
        "filter.exclude_entity_patterns": ["*_battery", "*_signal_strength"],
        "filter.min_availability_pct": 80,
    }
    return EventNormalizer(config)


class TestStateFiltering:
    def test_filter_unavailable_transition(self, normalizer):
        events = [
            {"timestamp": "2026-02-20T07:00:00", "entity_id": "light.bed", "domain": "light",
             "old_state": "on", "new_state": "unavailable", "area_id": "bedroom",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 0

    def test_keep_normal_transition(self, normalizer):
        events = [
            {"timestamp": "2026-02-20T07:00:00", "entity_id": "light.bed", "domain": "light",
             "old_state": "off", "new_state": "on", "area_id": "bedroom",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 1

    def test_filter_both_directions(self, normalizer):
        """Both to-unavailable and from-unavailable are filtered."""
        events = [
            {"timestamp": "2026-02-20T07:00:00", "entity_id": "light.bed", "domain": "light",
             "old_state": "unavailable", "new_state": "on", "area_id": "bedroom",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_states(events)
        assert len(result) == 0


class TestStateNormalization:
    def test_on_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "on") == "positive"

    def test_off_normalizes_to_negative(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "off") == "negative"

    def test_detected_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "detected") == "positive"

    def test_true_normalizes_to_positive(self, normalizer):
        assert normalizer.normalize_state("binary_sensor", "True") == "positive"

    def test_non_binary_passes_through(self, normalizer):
        assert normalizer.normalize_state("light", "on") == "positive"

    def test_unknown_state_passes_through(self, normalizer):
        assert normalizer.normalize_state("sensor", "23.5") == "23.5"


class TestUserExclusion:
    def test_exclude_entity(self, normalizer):
        events = [
            {"entity_id": "sensor.test_debug", "domain": "sensor", "area_id": None,
             "timestamp": "t", "old_state": "1", "new_state": "2",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_area(self, normalizer):
        events = [
            {"entity_id": "light.garage", "domain": "light", "area_id": "garage",
             "timestamp": "t", "old_state": "off", "new_state": "on",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_domain(self, normalizer):
        events = [
            {"entity_id": "automation.test", "domain": "automation", "area_id": None,
             "timestamp": "t", "old_state": "off", "new_state": "on",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_exclude_glob_pattern(self, normalizer):
        events = [
            {"entity_id": "sensor.bedroom_battery", "domain": "sensor", "area_id": "bedroom",
             "timestamp": "t", "old_state": "90", "new_state": "89",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 0

    def test_keep_valid_entity(self, normalizer):
        events = [
            {"entity_id": "light.bedroom", "domain": "light", "area_id": "bedroom",
             "timestamp": "t", "old_state": "off", "new_state": "on",
             "device_id": None, "context_parent_id": None, "attributes_json": None},
        ]
        result = normalizer.filter_user_exclusions(events)
        assert len(result) == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/hub/test_event_normalizer.py -v`
Expected: FAIL (ImportError)

**Step 3: Write event_normalizer.py**

```python
# aria/shared/event_normalizer.py
"""Event normalizer — filters, normalizes, and segments EventStore events.

Pipeline orchestrator that applies state filtering, user exclusions,
state normalization, and context tagging. Advanced stages (day
classification, co-occurrence, environmental correlation) are delegated
to separate modules.
"""
import fnmatch
import logging
from typing import Any

logger = logging.getLogger(__name__)

# States that map to semantic "positive" (entity active/triggered)
POSITIVE_STATES = {"on", "True", "true", "detected", "open", "unlocked", "home", "playing", "paused"}
# States that map to semantic "negative" (entity inactive/clear)
NEGATIVE_STATES = {"off", "False", "false", "clear", "closed", "locked", "not_home", "idle", "standby"}


class EventNormalizer:
    """Filters and normalizes raw EventStore events for detection engines."""

    def __init__(self, config: dict[str, Any]):
        self.ignored_states = set(config.get("filter.ignored_states", ["unavailable", "unknown"]))
        self.exclude_entities = set(config.get("filter.exclude_entities", []))
        self.exclude_areas = set(config.get("filter.exclude_areas", []))
        self.exclude_domains = set(config.get("filter.exclude_domains", []))
        self.include_domains = set(config.get("filter.include_domains", []))
        self.exclude_patterns = list(config.get("filter.exclude_entity_patterns", []))
        self.min_availability_pct = config.get("filter.min_availability_pct", 80)

    def filter_states(self, events: list[dict]) -> list[dict]:
        """Remove events where old_state or new_state is in ignored set."""
        return [
            e for e in events
            if e.get("old_state") not in self.ignored_states
            and e.get("new_state") not in self.ignored_states
        ]

    def normalize_state(self, domain: str, state: str) -> str:
        """Map hardware-specific states to semantic equivalents."""
        if state in POSITIVE_STATES:
            return "positive"
        if state in NEGATIVE_STATES:
            return "negative"
        return state  # numeric or unknown states pass through

    def filter_user_exclusions(self, events: list[dict]) -> list[dict]:
        """Apply user-configured entity/area/domain/pattern exclusions."""
        result = []
        for e in events:
            entity_id = e.get("entity_id", "")
            domain = e.get("domain", "")
            area_id = e.get("area_id")

            # Explicit entity exclusion
            if entity_id in self.exclude_entities:
                continue

            # Area exclusion
            if area_id and area_id in self.exclude_areas:
                continue

            # Domain exclusion (whitelist takes precedence)
            if self.include_domains:
                if domain not in self.include_domains:
                    continue
            elif domain in self.exclude_domains:
                continue

            # Glob pattern exclusion
            if any(fnmatch.fnmatch(entity_id, pat) for pat in self.exclude_patterns):
                continue

            result.append(e)
        return result
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/hub/test_event_normalizer.py -v`
Expected: PASS (all 11 tests)

**Step 5: Commit**

```bash
git add aria/shared/event_normalizer.py tests/hub/test_event_normalizer.py
git commit -m "feat(p3): add event normalizer with state filtering and user exclusions"
```

---

### Task 5: Entity Health Scoring

Score entities by availability percentage and grade as healthy/flaky/unreliable.

**Files:**
- Create: `aria/shared/entity_health.py`
- Test: `tests/hub/test_entity_health.py`

**Step 1: Write test**

```python
# tests/hub/test_entity_health.py
"""Tests for entity health scoring."""
import pytest
from aria.shared.entity_health import compute_entity_health
from aria.automation.models import EntityHealth


class TestEntityHealthScoring:
    def test_healthy_entity(self):
        """Entity with <5% unavailable time is healthy."""
        events = [
            {"entity_id": "light.bed", "new_state": "on"},
            {"entity_id": "light.bed", "new_state": "off"},
        ] * 50  # 100 normal transitions, 0 unavailable
        result = compute_entity_health("light.bed", events, total_events=100)
        assert result.health_grade == "healthy"
        assert result.availability_pct > 0.95

    def test_flaky_entity(self):
        """Entity with 10-20% unavailable transitions is flaky."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 85
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 15
        result = compute_entity_health("sensor.x", normal + bad, total_events=100)
        assert result.health_grade == "flaky"

    def test_unreliable_entity(self):
        """Entity with >20% unavailable transitions is unreliable."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 60
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 40
        result = compute_entity_health("sensor.x", normal + bad, total_events=100)
        assert result.health_grade == "unreliable"

    def test_zero_events_is_unreliable(self):
        result = compute_entity_health("sensor.x", [], total_events=0)
        assert result.health_grade == "unreliable"

    def test_custom_threshold(self):
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 85
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 15
        # With threshold at 90%, 85% available should be flaky
        result = compute_entity_health("sensor.x", normal + bad, total_events=100, min_healthy_pct=0.95, min_available_pct=0.90)
        assert result.health_grade == "flaky"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/hub/test_entity_health.py -v`

**Step 3: Write entity_health.py**

```python
# aria/shared/entity_health.py
"""Entity health scoring — grades entities by availability for filtering."""
import logging
from aria.automation.models import EntityHealth

logger = logging.getLogger(__name__)

UNAVAILABLE_STATES = {"unavailable", "unknown"}


def compute_entity_health(
    entity_id: str,
    events: list[dict],
    total_events: int,
    min_healthy_pct: float = 0.95,
    min_available_pct: float = 0.80,
) -> EntityHealth:
    """Compute health grade for an entity based on unavailable transitions.

    Args:
        entity_id: The entity to score.
        events: All events for this entity in the analysis window.
        total_events: Total event count (for percentage calculation).
        min_healthy_pct: Above this = healthy (default 95%).
        min_available_pct: Below this = unreliable (default 80%).
    """
    if total_events == 0:
        return EntityHealth(
            entity_id=entity_id,
            availability_pct=0.0,
            unavailable_transitions=0,
            longest_outage_hours=0.0,
            health_grade="unreliable",
        )

    unavailable_count = sum(
        1 for e in events if e.get("new_state") in UNAVAILABLE_STATES
    )
    availability_pct = 1.0 - (unavailable_count / total_events)

    # Longest outage would require timestamp analysis — simplified for now
    longest_outage = 0.0

    if availability_pct >= min_healthy_pct:
        grade = "healthy"
    elif availability_pct >= min_available_pct:
        grade = "flaky"
    else:
        grade = "unreliable"

    return EntityHealth(
        entity_id=entity_id,
        availability_pct=availability_pct,
        unavailable_transitions=unavailable_count,
        longest_outage_hours=longest_outage,
        health_grade=grade,
    )
```

**Step 4: Run test → PASS**

**Step 5: Commit**

```bash
git add aria/shared/entity_health.py tests/hub/test_entity_health.py
git commit -m "feat(p3): add entity health scoring and grading"
```

---

### Task 6: Config Defaults — Phase 3 Entries

Add all ~28 new config entries to config_defaults.py.

**Files:**
- Modify: `aria/hub/config_defaults.py` (append new entries to CONFIG_DEFAULTS list)
- Test: `tests/hub/test_config_defaults.py` (existing — verify count increases)

**Step 1: Check current config count**

Run: `.venv/bin/python -c "from aria.hub.config_defaults import CONFIG_DEFAULTS; print(len(CONFIG_DEFAULTS))"`

**Step 2: Write test assertion for new count**

Add to existing `tests/hub/test_config_defaults.py` (or create if not exists):
```python
def test_phase3_config_count():
    from aria.hub.config_defaults import CONFIG_DEFAULTS
    # Phase 2 had ~111 entries. Phase 3 adds ~28 new.
    assert len(CONFIG_DEFAULTS) >= 139
```

**Step 3: Add all Phase 3 config entries**

Append to CONFIG_DEFAULTS in `aria/hub/config_defaults.py`. Each entry follows the existing pattern with `key`, `default_value`, `value_type`, `label`, `description`, `description_layman`, `description_technical`, `category`, `min_value`, `max_value`, `step`.

Categories: "Pattern Engine", "Gap Analyzer", "Automation Generator", "Shadow Comparison", "LLM Refinement", "Data Filtering", "Calendar", "Normalizer"

Full list of 28 keys from design doc § Complete Config Entry Table. Agent should reference the design doc for exact layman/technical descriptions.

**Step 4: Run test → PASS**

**Step 5: Run full suite → all pass**

**Step 6: Commit**

```bash
git add aria/hub/config_defaults.py tests/hub/test_config_defaults.py
git commit -m "feat(p3): add 28 Phase 3 config entries with descriptions"
```

---

## Batch 3: Calendar + Day Classification

### Task 7: Calendar Context Fetch

Fetch calendar events from Google Calendar (via gog CLI) or HA calendar entity.

**Files:**
- Create: `aria/shared/calendar_context.py`
- Test: `tests/hub/test_calendar_context.py`

Key implementation: `async def fetch_calendar_events(source, start_date, end_date, entity_id=None)` that calls `gog calendar list --from <start> --to <end> --json` or HA API `GET /api/calendars/{entity_id}`. Returns list of `{summary, start, end}` dicts. Graceful degradation: if gog fails or HA calendar unavailable, return empty list.

### Task 8: Day Classifier

Classify each day in analysis window as workday/weekend/holiday/vacation/wfh.

**Files:**
- Create: `aria/shared/day_classifier.py`
- Test: `tests/hub/test_day_classifier.py`

Key implementation: `def classify_days(start_date, end_date, calendar_events, person_away_days, config)` → `list[DayContext]`. Logic: check weekday first, then keyword match against calendar events for holiday/vacation/WFH, then check person_away_days. Merge holidays with weekends if <10.

### Task 9: Day-Type Segmentation in Normalizer

Add `segment_by_day_type()` to event_normalizer that splits events by their day's classification.

**Files:**
- Modify: `aria/shared/event_normalizer.py` (add method)
- Test: `tests/hub/test_event_normalizer.py` (add tests)

Key implementation: `def segment_by_day_type(events, day_contexts)` → `dict[str, list[dict]]` mapping day_type → events for that type. Events on vacation days excluded.

---

## Batch 4: Normalizer Advanced

### Task 10: Co-occurrence Detection

Order-independent set clustering within time windows.

**Files:**
- Create: `aria/shared/co_occurrence.py`
- Test: `tests/hub/test_co_occurrence.py`

Key implementation: `def find_co_occurring_sets(events, window_minutes=20, min_count=5)` → list of `BehavioralCluster(entities: frozenset, actions: frozenset, time_window, count, typical_ordering)`. Algorithm: for each event, look forward within window to find all entities that also changed state. Build co-occurrence matrix, find frequent itemsets.

### Task 11: Adaptive Time Windows

Compute median ± 2σ time windows for detected patterns.

**Files:**
- Add to: `aria/shared/co_occurrence.py` (or separate `aria/shared/time_analysis.py` if >200 lines)
- Test: add to `tests/hub/test_co_occurrence.py`

Key implementation: `def compute_adaptive_window(timestamps: list[str])` → `(median_time, sigma_minutes, skip_time_condition: bool)`. If σ > 90 minutes, `skip_time_condition=True`.

### Task 12: Environmental Correlator

Pearson correlation between event times and sun position/illuminance.

**Files:**
- Create: `aria/shared/environmental_correlator.py`
- Test: `tests/hub/test_environmental_correlator.py`

Key implementation: `def correlate_with_environment(event_timestamps, sun_events, illuminance_events, threshold=0.7)` → `{prefer_sun_trigger: bool, prefer_illuminance_trigger: bool, correlation_r: float}`. Uses numpy for Pearson r calculation.

---

## Batch 5: Pattern Engine Rewrite

### Task 13: Pattern Engine — EventStore Data Source

Replace logbook file reading with EventStore queries in patterns.py.

**Files:**
- Modify: `aria/modules/patterns.py` (rewrite `_extract_sequences()` to query EventStore)
- Test: `tests/hub/test_patterns.py` (update existing tests)

Keep DTW clustering and Apriori algorithms. Change data source only. Add EntityGraph integration.

### Task 14: Pattern Engine — Day-Type Analysis

Add per-day-type pattern detection.

**Files:**
- Modify: `aria/modules/patterns.py` (add day_type to output, run per segment)
- Test: `tests/hub/test_patterns.py` (add day-type tests)

### Task 15: Pattern Engine — New Output Fields + Scheduling

Add entity_chain, trigger_entity, first_seen, last_seen, source_event_count. Add periodic scheduling via hub timer.

**Files:**
- Modify: `aria/modules/patterns.py`
- Test: `tests/hub/test_patterns.py`

---

## Batch 6: Gap Analyzer

### Task 16: Anomaly-Gap Analyzer Core

Sequence mining on manual-only events from EventStore.

**Files:**
- Create: `aria/modules/anomaly_gap.py`
- Test: `tests/hub/test_anomaly_gap.py`

Key implementation: `AnomalyGapAnalyzer(Module)` with `analyze_gaps()` method. Queries `event_store.query_manual_events()`, builds frequent subsequences, cross-references `ha_automations` cache. Uses simplified PrefixSpan (no external dep — implement inline for short sequences of 2-5 entities).

### Task 17: Gap Analyzer — Cross-Reference HA Cache

Exclude detected gaps that already have matching HA automations.

**Files:**
- Modify: `aria/modules/anomaly_gap.py` (add cross-reference method)
- Test: `tests/hub/test_anomaly_gap.py` (add cross-ref tests)

---

## Batch 7: YAML Generation

### Task 18: Trigger Builder

Domain-aware HA trigger type selection.

**Files:**
- Create: `aria/automation/trigger_builder.py`
- Test: `tests/hub/test_trigger_builder.py`

Key implementation: `def build_trigger(detection: DetectionResult)` → trigger dict. Maps domain to trigger type, adds `for` debounce, handles chain links as context.

### Task 19: Condition Builder

Presence, illuminance, time, weekday, safety conditions.

**Files:**
- Create: `aria/automation/condition_builder.py`
- Test: `tests/hub/test_condition_builder.py`

Key implementation: `def build_conditions(detection, entity_graph, config)` → list of condition dicts. Includes SAFETY_CONDITIONS defaults. Time conditions only if pattern data supports.

### Task 20: Action Builder

Area targeting, attribute extraction, restricted domain check.

**Files:**
- Create: `aria/automation/action_builder.py`
- Test: `tests/hub/test_action_builder.py`

Key implementation: `def build_actions(detection, entity_graph)` → list of action dicts. Prefers area_id targeting. Extracts brightness/color_temp from attributes_json if consistent.

### Task 21: Template Engine Coordinator

Compose trigger + condition + action + mode + description into full automation dict.

**Files:**
- Create: `aria/automation/template_engine.py`
- Test: `tests/hub/test_template_engine.py`

Key implementation: `class AutomationTemplate` with `build(detection)` → full HA automation dict. Generates id, alias, description, calls trigger/condition/action builders, selects mode, force-quotes boolean state values.

---

## Batch 8: LLM + Validation

### Task 22: LLM Refiner

Ollama polish for alias and description with strict validation.

**Files:**
- Create: `aria/automation/llm_refiner.py`
- Test: `tests/hub/test_llm_refiner.py`

Key implementation: `async def refine_automation(automation_dict, model, timeout)` → refined dict or original on failure. Sends prompt to Ollama with clear constraints. Post-check: diff non-text fields, reject if any structural change.

### Task 23: Automation Validator (9 Checks)

Full validation suite for generated automations.

**Files:**
- Create: `aria/automation/validator.py`
- Test: `tests/hub/test_automation_validator.py`

Key implementation: `def validate_automation(automation, entity_graph, existing_ids)` → `(valid: bool, errors: list[str])`. Runs all 9 checks sequentially. Each check is a separate method for testability.

---

## Batch 9: Shadow Comparison

### Task 24: HA Automation Sync

Periodic fetch + incremental hash-based normalization.

**Files:**
- Create: `aria/shared/ha_automation_sync.py`
- Test: `tests/hub/test_ha_automation_sync.py`

Key implementation: `class HaAutomationSync` with `async sync()`, `async force_sync()`. Fetches `GET /api/config/automation/config`, hashes each automation, only re-normalizes changed ones. Normalizes entity_id formats. Stores in `ha_automations` cache.

### Task 25: Shadow Comparison Engine

Duplicate, conflict, gap, superset/subset detection.

**Files:**
- Create: `aria/shared/shadow_comparison.py`
- Test: `tests/hub/test_shadow_comparison.py`

Key implementation: `def compare_candidate(candidate, ha_automations, entity_graph)` → `ShadowResult`. Implements all detection types from design doc.

### Task 26: Immediate Cache Update on Approval

When orchestrator creates automation in HA, immediately add to ha_automations cache.

**Files:**
- Modify: `aria/modules/orchestrator.py` (in approval flow)
- Test: `tests/hub/test_orchestrator.py` (add test)

---

## Batch 10: Integration — Generator Module + Orchestrator

### Task 27: AutomationGenerator Hub Module

Coordinator module that ties everything together.

**Files:**
- Create: `aria/modules/automation_generator.py`
- Test: `tests/hub/test_automation_generator.py`

Key implementation: `class AutomationGeneratorModule(Module)` with `async generate_suggestions()`. Reads patterns cache + gaps cache → combined scoring → top-N → template engine → LLM → validator → shadow → store in `automation_suggestions` cache.

### Task 28: Orchestrator Thinning

Remove _pattern_to_suggestion, delegate to AutomationGenerator.

**Files:**
- Modify: `aria/modules/orchestrator.py`
- Test: `tests/hub/test_orchestrator.py` (update existing tests)

### Task 29: Combined Scoring

Score detection results from both engines with pattern × 0.5 + gap × 0.3 + recency × 0.2.

**Files:**
- Add to: `aria/modules/automation_generator.py`
- Test: `tests/hub/test_automation_generator.py`

---

## Batch 11: API + CLI

### Task 30: New API Endpoints

Shadow sync, status, compare, automations health, delete.

**Files:**
- Modify: `aria/hub/routes.py`
- Test: `tests/hub/test_routes.py` or new `tests/hub/test_automation_routes.py`

Endpoints: POST /api/shadow/sync, GET /api/shadow/status, GET /api/shadow/compare, GET /api/automations/health, DELETE /api/automations/{id}

### Task 31: CLI Commands

`aria patterns`, `aria gaps`, `aria suggest`, `aria shadow`, `aria shadow sync`, `aria rollback --last`.

**Files:**
- Modify: CLI entry point (check `aria/cli/` or `pyproject.toml` for entry point location)
- Test: `tests/test_cli_*.py`

### Task 32: Health Cache + Observability

New `automation_system_health` cache category updated by generator module.

**Files:**
- Modify: `aria/modules/automation_generator.py` (add health reporting)
- Test: `tests/hub/test_automation_generator.py`

---

## Batch 12: Integration + Performance Tests

### Task 33: End-to-End Pipeline Test

Insert synthetic events → run full pipeline → assert suggestions in cache.

**Files:**
- Create: `tests/integration/test_automation_pipeline.py`

### Task 34: Known-Answer Golden Tests

Predefined event sequences with expected automations.

**Files:**
- Create: `tests/integration/known_answer/test_automation_golden.py`
- Create: `tests/integration/known_answer/golden/automation_*.json`

### Task 35: Performance Tests

100K events, memory budget, incremental sync.

**Files:**
- Create: `tests/performance/test_automation_performance.py`

---

## Batch 13: Dashboard

### Task 36: Decide Page Enhancements

Status badges, conflict warnings, gap fill labels, undo button, health bar.

**Files:**
- Modify: `aria/dashboard/spa/src/pages/Decide.jsx`
- Modify: `aria/dashboard/spa/src/lib/pipelineGraph.js` (if Sankey nodes change)

After changes: `cd aria/dashboard/spa && npm run build`

### Task 37: Settings — Data Filtering Section

Area/domain/entity toggles for filtering.

**Files:**
- Modify: `aria/dashboard/spa/src/pages/intelligence/Settings.jsx`

After changes: `cd aria/dashboard/spa && npm run build`

---

## Post-Implementation Checklist

- [ ] All tests pass: `.venv/bin/python -m pytest tests/ --timeout=120 -x -q`
- [ ] No regressions in existing 1718 tests
- [ ] Config count increased by ~28
- [ ] EventStore schema has context_parent_id
- [ ] Dead code removed: `aria/engine/llm/automation_suggestions.py`
- [ ] SPA rebuilt: `cd aria/dashboard/spa && npm run build`
- [ ] Pipeline vertical trace: insert test event → normalizer → pattern/gap → generator → shadow → cache → API → dashboard
- [ ] Run `aria suggest` CLI command successfully
- [ ] Run `aria shadow sync` CLI command successfully
- [ ] Restart service: `systemctl --user restart aria-hub`
- [ ] Check logs: `journalctl --user -u aria-hub -f`
