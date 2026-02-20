# ARIA Roadmap 2.0 — Design Document

**Date:** 2026-02-20
**Status:** Approved
**Scope:** Full architectural redesign — event-stream-first pipeline, HA-native automation output, intelligence analyst I&W framework

---

## Vision

Transform ARIA from an aggregate-snapshot ML system into an event-stream-first intelligence platform that:
1. Ingests every HA entity state change as a timestamped event
2. Models the home as HA does: Entity → Device → Area hierarchy
3. Detects behavioral states (not time slots) using indicator & warning chains
4. Generates full HA-native automation YAML validated against existing automations
5. Degrades gracefully — core pipeline works without LLM, without internet, without anything but HA

---

## Architecture Overview

```
HA WebSocket (state_changed)
        │
        ▼
   Event Store (SQLite events.db)
        │
   ┌────┴─────────────────┐
   │                       │
   ▼                       ▼
Segment Builder         I&W Pattern Miner
(ML feature vectors)    (behavioral state detection)
   │                       │
   ▼                       ▼
Unified ML Engine       Capability Lifecycle
(predictions,           (seed→emerging→confirmed→mature)
 anomaly detection)          │
   │                       │
   └────────┬──────────────┘
            │
            ▼
   Automation Generator
   (HA-native YAML)
            │
      ┌─────┴─────┐
      │            │
      ▼            ▼
  HA Shadow     LLM Refinement
  Comparison    (optional)
      │            │
      └─────┬──────┘
            │
            ▼
   Decide Page (approve/reject)
            │
            ▼
   HA REST API (create automation)
```

---

## Locked-In Decisions

| Decision | Choice |
|----------|--------|
| Schema depth | Full HA mirror — entity→device→area hierarchy |
| Data strategy | Event-stream primary — snapshots derived from events |
| Automation triggers | Pattern confidence + anomaly-gap detection (both) |
| HA validation | Shadow comparison + prediction scoring (both) |
| Presence weights | Per-signal-type user-configurable weights |
| Synthetic testing | Simulated event streams + weight/hyperparameter sweeps |
| Organic capabilities | Auto-discovery + emergent composites via I&W framework |
| ML integration | Unified real-time ML in hub; batch engine for deep analysis only |
| LLM role | Multi-layer: LLM-optional core → multi-model routing → per-task config → graceful degradation |
| FE/BE sync | Paired agents + worktree isolation + post-batch sync check |
| User prompt | Deferred to v2.1 |
| Settings UX | Every setting: layman + technical explanation + min/max examples |

---

## Phase 1: Event Store + Entity Graph (~2 weeks)

### Event Store

New SQLite database (`events.db`) storing every `state_changed` event from HA WebSocket.

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,          -- ISO 8601
    entity_id TEXT NOT NULL,
    domain TEXT NOT NULL,             -- extracted from entity_id
    old_state TEXT,
    new_state TEXT,
    device_id TEXT,                   -- resolved at ingest
    area_id TEXT,                     -- resolved at ingest (entity→device→area)
    attributes_json TEXT              -- optional, key attributes like brightness
);
CREATE INDEX idx_events_ts ON events(timestamp);
CREATE INDEX idx_events_entity ON events(entity_id, timestamp);
CREATE INDEX idx_events_area ON events(area_id, timestamp);
CREATE INDEX idx_events_domain ON events(domain, timestamp);
```

- **Retention:** 90 days rolling (configurable). Older events aggregated into daily summaries before deletion.
- **Writer:** `activity_monitor` — already subscribes to `state_changed`. Change: persist to `events.db` first, then aggregate.
- **Readers:** ML engine (segment builder), patterns module (sequence mining), orchestrator (automation generation), shadow engine (prediction scoring).

### Entity Graph

Centralized `EntityGraph` class in `aria/shared/entity_graph.py`:

- `graph.get_area(entity_id)` → area_id (entity→device→area chain)
- `graph.get_device(entity_id)` → device info
- `graph.entities_in_area(area_id)` → list of entity_ids
- `graph.entities_by_domain(domain)` → list of entity_ids
- Refreshed from discovery cache on `cache_updated` events

Replaces 3 independent entity→area resolution implementations (discovery, presence, snapshot collector) with one source of truth.

### Snapshot Derivation

Current snapshots become derived views computed from event store + current HA state. `snapshot.py` still produces the same JSON output (backward compatible) but reads event counts/transitions from `events.db` instead of separate HA API calls.

---

## Phase 2: Unified ML Engine + Presence Weights (~2 weeks)

### Unified ML Engine

Merge batch engine gradient boosting + hub ml_engine LightGBM into a single hub-based ML system training on event-window segments.

**Segment Builder** reads from `events.db`:
- Current aggregate features (backward compatible): `lights_on`, `power_watts`, `devices_home`
- Event-derived features: `event_count`, `light_transitions`, `motion_events`, `unique_entities_active`, `per_area_activity`, `domain_entropy`
- Existing rolling features: `rolling_{1,3,6}h_{event_count, domain_entropy, dominant_domain_pct, trend}`

Segments generated every 15 min (configurable). Training on accumulated segments with GradientBoosting, LightGBM, IsolationForest. Incremental LightGBM adaptation on drift detection stays.

**Batch engine keeps:** Baselines, correlations, entity correlations, meta-learning (LLM), Prophet forecasting, SHAP attributions.

**Prediction targets evolve:** Add per-area and per-domain predictions beyond current `[power_watts, lights_on, devices_home, unavailable, useful_events]`.

### Presence User Weights

Make Bayesian signal weights user-configurable via settings:

- Config entries: `presence.weight.motion`, `presence.weight.camera_person`, `presence.weight.camera_face`, etc.
- Defaults match current hardcoded values (motion=0.9, camera_face=1.0, etc.)
- Decay times also configurable: `presence.decay.motion` (default 300s), etc.
- `presence.py` reads from config on each flush cycle instead of hardcoded dict

### Settings UX Pattern

Every setting follows this template:

```
Label: Motion Sensor Trust
Category: Presence Tracking

Layman: "How much should ARIA trust motion sensors? Higher means
motion alone can determine someone is in a room."

Technical: "Bayesian prior weight for motion-type signals in the
occupancy fusion algorithm. Range 0.0-1.0. Default 0.9."

Example at minimum (0.1): "Motion barely registers. ARIA needs
camera + device tracker + motion to confirm presence."

Example at maximum (1.0): "A single motion event = 100% confidence
someone is there. May cause false positives from pets."

Default: 0.9 | Min: 0.0 | Max: 1.0 | Step: 0.05
```

Applied to ALL settings (existing ~60+ and new ones).

---

## Phase 3: Automation Generator Rewrite (~2 weeks)

### Two Detection Engines

**Pattern Confidence:** From `patterns` module. "This event sequence repeats with >X% confidence." Detects: entity A state change reliably precedes entity B state change within a time window.

**Anomaly-Gap Detection:** New analyzer reads event store for repetitive manual actions: "You turned on kitchen_light 47 of 50 mornings between 6:45-7:15. This could be automated." Identifies the gap between what users do manually and what HA automates.

### HA-Native YAML Generation

Full HA automation schema output:

```yaml
- id: "aria_1708444800_bedroom_morning_light"
  alias: "Bedroom morning lights on motion"
  description: >
    ARIA detected: bedroom motion triggers bedroom light 85% of
    weekday mornings (6:45-7:15). Generated from 47 observations
    over 55 days.
  mode: single
  triggers:
    - trigger: state
      entity_id: binary_sensor.bedroom_motion
      to: "on"
      for: "00:00:05"
      id: morning_motion
  conditions:
    - condition: time
      after: "06:30:00"
      before: "07:30:00"
      weekday: [mon, tue, wed, thu, fri]
    - condition: state
      entity_id: person.justin
      state: home
    - condition: numeric_state
      entity_id: sensor.bedroom_illuminance
      below: 50
  actions:
    - action: light.turn_on
      target:
        area_id: bedroom
      data:
        brightness_pct: 80
        color_temp_kelvin: 4000
```

Design choices:
- `area_id` targets preferred over `entity_id` lists
- `for` duration on state triggers to prevent flapping
- Presence conditions when pattern correlates with person state
- Illuminance conditions when sensor data available
- Description cites observation data (count, confidence, date range)
- All 17 HA trigger types supported (state, numeric_state, time, sun, zone, etc.)
- `RESTRICTED_DOMAINS` (lock, alarm, cover) require explicit approval

### HA Automation Shadow Comparison

Fetches existing HA automations via REST API. Three checks before suggesting:

1. **Duplicate detection** — Existing automation covers this trigger→action pair? Skip.
2. **Conflict detection** — Existing automation does the opposite at same time? Flag conflict.
3. **Gap detection** — User has automation for kitchen motion→light but not hallway? Suggest filling gap.

### LLM Refinement Layer

Template-generated YAML optionally refined by LLM:
- Better aliases, natural language descriptions, condition optimization
- Fallback: template output ships as-is if Ollama unavailable
- Validated after refinement: must still be valid HA YAML

---

## Phase 4: I&W Framework + Organic Capabilities + Synthetic Testing (~2 weeks)

### Intelligence Analyst Approach: Indicator & Warning (I&W) Framework

Capabilities are **behavioral states** — recognizable patterns of life defined by indicator chains, not clock times.

```
Behavioral State: "Morning Routine"
├── Trigger Indicator: bedroom_motion ON (after >4h quiet)
├── Confirming Indicators:
│   ├── bathroom_motion ON within 10min
│   ├── kitchen_motion ON within 20min
│   └── coffee_maker power spike within 25min
├── Context: person.justin state = home
├── Typical duration: 30-60 min
├── Observed 43 times in 55 days (78% weekdays, 22% weekends)
└── Expected outcome: front_door opens (weekdays, 85%) OR
    TV turns on (weekends, 70%)
```

**Three indicator types:**

| Type | What It Detects | Example |
|------|----------------|---------|
| Trigger indicator | Initiating event of a behavioral state | Front door opens + person transitions to home |
| Confirming indicator | Events confirming state is active | Kitchen light on within 5 min of arrival |
| Deviation indicator | Absence of expected event | Person home 30 min, no lights = anomaly |

**Discovery process:**

1. **Sequence mining** on event store — frequently co-occurring entity state changes within time windows. Not "what at 7am" but "what after bedroom_motion after >4h quiet."
2. **Causal chain detection** — Does A reliably precede B? Granger causality or transfer entropy on entity event streams.
3. **Person attribution** — Link chains to person entities. Per-person vs universal vs nobody-home patterns.
4. **Location context** — Spatial path patterns (bedroom→bathroom→kitchen) vs room-local patterns (all kitchen events).

### Capability Lifecycle

```
SEED → EMERGING → CONFIRMED → MATURE → (DORMANT → REVIVED | RETIRED)
```

| Stage | Criteria | ARIA Action |
|-------|----------|-------------|
| Seed | 3+ observations | Track silently |
| Emerging | 7+ observations, >60% consistency | Show on dashboard, no automation |
| Confirmed | 15+ observations, >70% consistency, passes backtest | Generate automation suggestion |
| Mature | User approved OR 30+ observations >80% | Full confidence, anomaly baseline |
| Dormant | <3 observations in 30 days | Stop generating suggestions |
| Revived | 3+ new observations after dormant | Return to Emerging |
| Retired | 90 days dormant OR user rejected | Archived |

### Backtesting

When ARIA discovers an emerging capability:

1. **Historical replay:** Run indicator chain against last 90 days of events. Count executions, measure consistency, identify false triggers.
2. **Holdout validation:** 70/30 split. Train on 70%, predict on 30%.
3. **Counterfactual test:** "If this automation existed, how many manual actions would it have replaced?"

### Organic Capability Discovery

**Layer 1 — Domain Auto-Discovery:** Discovery scan creates base capabilities per entity domain. No hardcoded seed list.

**Layer 2 — Emergent Composites:** Multi-domain sequences detected by I&W framework become composite capabilities (e.g., "movie night" = lights dim + TV on + blinds close).

**Guardrails:**
- Minimum 5 observations before proposing composite
- Maximum 20 active composites (oldest/lowest-confidence pruned)
- User can archive/promote on Capabilities page
- Rejected automations downweight the source capability
- No hardcoded values anywhere — all thresholds configurable

### Synthetic Test Framework

**Type 1 — Simulated Event Streams (correctness):**
Generate realistic event sequences with known patterns. Feed into event store, run pipeline, assert patterns detected with minimum confidence. Known-answer approach.

**Type 2 — Weight/Hyperparameter Sweeps (optimization):**
Run real historical data through ARIA with different configurations in parallel. Compare output quality metrics. Report optimal configuration. CLI: `aria sweep --param <key> --values <csv>`.

---

## Phase 5: LLM Integration + Telegram Fixes (~1 week)

### Multi-Layer LLM Architecture

**Principle: LLM translates, ML decides. Pipeline works without LLM.**

**Layer 0 — Core pipeline (no LLM):** Event store → segment builder → ML → I&W detection → template YAML. Functional but utilitarian.

**Layer 1 — Per-task refinement:**

| Task | Model | Fallback |
|------|-------|----------|
| Automation YAML polish | HA-specific model | Template output |
| Anomaly explanation | deepseek-r1 | "Deviation: X was Y, expected Z" |
| Daily digest | Small/fast model | Structured text |
| Meta-learning report | deepseek-r1 | Skip auto-adjustment |

**Layer 2 — Model routing config:**

New settings category "LLM / Ollama":
- `llm.enabled` — master toggle
- `llm.automation_model` — HA-specific model for YAML
- `llm.reasoning_model` — deepseek-r1 for meta-learning/explanations
- `llm.summary_model` — fast model for digests
- `llm.temperature.automation` / `llm.temperature.reasoning`
- `llm.timeout`, `llm.queue_enabled`
- Each task individually toggleable

**Layer 3 — Graceful degradation:** Every LLM call wrapped with fallback to non-LLM output. Validated after refinement (must still be valid YAML/format).

### Telegram Fixes

**Unified sender** (`aria/shared/telegram.py`):
- Single async sender with retry + backoff
- Rate limiting, priority queue (CRITICAL > WARNING > INFO > DIGEST)
- Persistent cooldown in `hub.db` (not `/tmp/`)
- Health check: 3 consecutive failures → `telegram_healthy=false` in cache

**Rich digest format:**
- Inline keyboard buttons (View Dashboard, Snooze 24h)
- New behavioral states detected
- Automation suggestions pending review
- Anomaly alerts with LLM explanations
- Model accuracy trend

---

## Phase 6: Polish (~1 week)

### Settings UX Retrofit

- Add `layman_description`, `technical_description`, `example_min`, `example_max` to config table
- Populate for all ~60+ existing settings (migration script)
- New settings must include all fields (validation enforced)
- Settings page toggle: Simple view (layman) vs Advanced view (technical + examples)

### FE/BE Sync Tooling

**Layer 1 — Paired agents:** Backend changes spawn frontend agent (and vice versa). Both validated together.

**Layer 2 — Worktree isolation:** `git worktree` per Code Factory execution. Integration branch for multi-batch phases.

**Layer 3 — Post-batch sync check:** After each batch: `npm run build` + `pytest tests/integration/`. Block next batch on failure.

---

## Deferred to v2.1

- **Natural language user prompt:** "Make the house cozy when I get home after dark" → ARIA interprets intent → generates automation
- **Prediction scoring against automation outcomes:** When HA automation fires, check if ARIA predicted it
- **Blueprint generation:** Reusable patterns → HA blueprints for multi-room application

---

## Key Architectural Principles

1. **Event stream is the single source of truth.** Snapshots, segments, patterns all derive from stored events.
2. **Entity graph is centralized.** One `EntityGraph` class, no module-specific resolution logic.
3. **Behavioral states, not time slots.** I&W framework detects causal chains, not clock correlations.
4. **LLM translates, ML decides.** Core pipeline works without Ollama. LLM is enhancement, not dependency.
5. **Graceful degradation everywhere.** Every optional component has a fallback.
6. **No hardcoded values.** All thresholds, weights, and limits configurable with layman + technical explanations.
7. **HA-native output.** Automations follow HA schema exactly — `area_id` targets, proper triggers, `for` durations, presence conditions.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Event store growth (disk) | 90-day retention + daily aggregation of old events |
| SQLite write contention | WAL mode (already used for hub.db), single writer (activity_monitor) |
| ML memory with larger feature space | Hardware tier gating (existing), segment size limits |
| LLM unavailability | Every LLM task has non-LLM fallback |
| Capability explosion | Max 20 composites, lifecycle pruning, user curation |
| FE/BE drift during development | Three-layer defense: paired agents + worktree + sync check |
| Backward compatibility | Snapshot format unchanged, existing tests as regression suite |
