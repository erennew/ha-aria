# Phase 4: I&W Framework + Organic Capabilities + Synthetic Testing — Design Document

**Date:** 2026-02-21
**Status:** Approved
**Scope:** Behavioral state detection via indicator chains, capability lifecycle management, organic discovery with composites, backtesting engine, synthetic test framework
**Depends on:** Phase 1 (EventStore, EntityGraph), Phase 2 (SegmentBuilder, presence weights), Phase 3 (patterns.py rewrite, gap analyzer, co_occurrence, automation generator)

---

## Vision

Transform ARIA's pattern detection from "entity A precedes entity B" into behavioral state intelligence: detect that "Morning Routine is active," track its lifecycle from seed observation to mature automation candidate, and validate it through backtesting before suggesting automations.

**Intelligence analyst parallel:** This implements the Indicator & Warning (I&W) methodology — the pattern definition (collection plan) is separated from observations (collection record), with real-time monitoring against known indicator chains.

---

## Data Model (Three-Layer)

### Layer 1 — Indicator (atomic detection unit)

```python
@dataclass(frozen=True)
class Indicator:
    entity_id: str
    role: str                        # trigger | confirming | deviation

    # Detection mode
    mode: str                        # state_change | quiet_period | threshold

    # For state_change: entity transitions to this state
    expected_state: str | None = None

    # For quiet_period: no events from entity for this duration
    quiet_seconds: int | None = None

    # For threshold: numeric entity crosses boundary
    threshold_value: float | None = None
    threshold_direction: str | None = None  # above | below

    # Timing relative to trigger (not ordinal position)
    max_delay_seconds: int = 0       # 0 = is the trigger itself

    # Observed reliability
    confidence: float = 0.0          # How often this fires when state is active
```

Handles three detection patterns:
- `state_change`: "bedroom_motion goes ON" → `expected_state="on"`
- `quiet_period`: "after >4h of no events" → `quiet_seconds=14400`
- `threshold`: "illuminance below 50 lux" → `threshold_value=50, threshold_direction="below"`

### Layer 2 — BehavioralStateDefinition (immutable pattern)

```python
@dataclass(frozen=True)
class BehavioralStateDefinition:
    id: str                          # deterministic hash of indicators
    name: str                        # "Morning Routine (Bedroom, Workday)"

    trigger: Indicator               # Single trigger indicator
    trigger_preconditions: list[Indicator]  # e.g. quiet_period before trigger
    confirming: list[Indicator]      # Expected follow-on events
    deviations: list[Indicator]      # Absence = anomaly signal

    # Context constraints
    areas: frozenset[str]
    day_types: frozenset[str]        # workday | weekend | holiday
    person_attribution: str | None   # person.X | None (universal)

    # Temporal bounds
    typical_duration_minutes: float
    expected_outcomes: tuple[dict, ...]  # ({entity_id, state, probability}, ...)

    # Composition
    composite_of: tuple[str, ...] = ()  # IDs of child BehavioralStates
```

Frozen and hashable. Once discovered, definitions are immutable — pattern evolution creates new definitions. The deterministic ID = `hash(trigger_entity + sorted(confirming_entities) + area + day_type)`.

### Layer 3 — BehavioralStateTracker (mutable runtime)

```python
@dataclass
class BehavioralStateTracker:
    definition_id: str               # FK to BehavioralStateDefinition
    lifecycle: str                   # seed|emerging|confirmed|mature|dormant|retired

    # Observation stats
    observation_count: int = 0
    consistency: float = 0.0
    first_seen: str = ""
    last_seen: str = ""

    # Lifecycle transitions
    lifecycle_history: list[dict] = field(default_factory=list)

    # Backtesting
    backtest_result: dict | None = None

    # User interaction
    user_feedback: str | None = None  # approved | rejected

    # Automation linkage
    automation_suggestion_id: str | None = None
    automation_status: str | None = None  # pending|approved|active|rejected
```

### Real-Time — ActiveState (in-memory only)

```python
@dataclass
class ActiveState:
    definition_id: str
    trigger_time: str                # When trigger fired
    matched_confirming: list[str]    # Entity IDs that matched so far
    pending_confirming: list[str]    # Still waiting for these
    window_expires: str              # When to give up waiting

    @property
    def match_ratio(self) -> float:
        total = len(self.matched_confirming) + len(self.pending_confirming)
        return len(self.matched_confirming) / total if total else 0.0
```

### Storage

| Object | Where | Why |
|--------|-------|-----|
| BehavioralStateDefinition | `hub.db` table `behavioral_state_definitions` | Derived intelligence, JSON for indicator lists |
| BehavioralStateTracker | `hub.db` table `behavioral_state_trackers` | Mutable, frequently updated |
| ActiveState | In-memory only | Ephemeral, reconstructed on restart via cold-start replay |
| State co-activations | `hub.db` table `state_co_activations` | Composite discovery tracking |

---

## Detection Architecture

### Discovery Engine (`aria/iw/discovery.py`)

Runs periodically (default: every 6 hours, configurable via `iw.discovery_interval_hours`).

**Three-stage pipeline:**

**Stage 1 — Sequence Mining:** Consumes outputs from both `patterns.py` (DTW + Apriori multi-entity sequences with entity chains and day-type segmentation) and `anomaly_gap.py` (solo toggles for single-entity repetitive behaviors). Feeds through `event_normalizer.py` to exclude high-frequency sensor noise.

**Stage 2 — Indicator Chain Construction:** For each pattern with confidence above threshold (`iw.min_discovery_confidence`, default 0.60):
- Trigger = first entity in chain (trigger_entity from patterns.py)
- Confirming = remaining entities, max_delay computed from co_occurrence adaptive windows
- Preconditions = quiet_period detection (measure gap before trigger across observations)
- Deviations = entities that appear in >70% of observations but aren't in the chain
- Precondition timing recomputed from last 30 days of observations (handles temporal drift)

**Stage 3 — Deduplication + Merge:** Compare new definitions against existing:
- Same trigger entity + same area + overlapping confirming set
- If >60% indicator overlap → merge (update confidence, add new indicators)
- If <60% overlap → new definition
- Deterministic ID prevents duplicates across runs

### Real-Time Detector (`aria/iw/detector.py`)

Hub module, subscribes to `state_changed` events with domain filtering (lesson #39).

**Internal state:**
- `definitions: dict[str, BehavioralStateDefinition]` — loaded from hub.db
- `entity_index: dict[str, list[str]]` — entity_id → definition_ids (O(1) lookup per event)
- `active_states: dict[str, ActiveState]` — currently tracking partial matches
- `person_states: dict[str, str]` — person.X → home/away

**Event processing (per state_changed):**
1. Look up `entity_index[entity_id]` → candidate definitions
2. For each candidate:
   - If entity is trigger and preconditions met → create ActiveState
   - If entity is confirming and ActiveState exists → update matched list
   - If entity is deviation target and ActiveState exists → note deviation
3. If entity is person.* → update person_states, terminate person-attributed ActiveStates if person leaves

**Timer (every 60s):**
1. Expire ActiveStates past `window_expires`
2. Expired states with `match_ratio > threshold` (`iw.min_match_ratio`, default 0.50) → record observation in tracker
3. Expired states below threshold → discard

**Definition refresh:** On discovery engine completion, reload definitions and rebuild entity_index. No restart required.

**Cold-start on restart:** Scan last `max(typical_duration_minutes)` of EventStore and replay through detector. Prevents losing in-progress states on hub restart (lesson #5).

**Domain filter:** Build domain set from all entity_ids across all definitions. Register only those domains with the subscriber. Rebuilds on definition refresh.

### Lifecycle Manager (`aria/iw/lifecycle.py`)

Called after each observation is recorded. Evaluates promotion/demotion.

**Promotion rules:**

| Transition | Criteria |
|------------|----------|
| seed → emerging | observation_count ≥ 7 AND consistency ≥ 0.60 AND observation_density ≥ 0.3/active-day |
| emerging → confirmed | observation_count ≥ 15 AND consistency ≥ 0.70 AND backtest PASSES (required gate) AND density ≥ 0.5/active-day |
| confirmed → mature | user approved OR (observation_count ≥ 30 AND consistency ≥ 0.80) |

Observation density = observations per day-type-matching day (excludes vacation via `day_classifier.py`). Prevents promoting low-density patterns (1/week for 15 weeks) that happen to meet count thresholds.

**Demotion rules:**

| Transition | Criteria |
|------------|----------|
| any → dormant | < 3 observations in last 30 active days (vacation days excluded via day_classifier) |
| dormant → revived | 3+ new observations → returns to emerging |
| dormant (90 days) → retired | Archived, removed from real-time detector |

**Automation rejection feedback:**
- First rejection of automation from this state: +10% promotion threshold penalty
- Second rejection: demote to seed
- Prevents nagging with repeated suggestions from the same flawed pattern

**Side effects by lifecycle stage:**

| Stage | Action |
|-------|--------|
| emerging | Show on dashboard Observe page |
| confirmed | Auto-trigger backtest → if passes, generate automation suggestion via Phase 3 pipeline |
| mature | Use as anomaly baseline (deviation from mature state triggers alert) |
| retired | Remove from real-time detector, archive definition |

---

## Organic Discovery + Composites

### Layer 1 — Domain Auto-Discovery

No hardcoded seed list. Discovery engine:
1. Queries EntityGraph for all domains with >5 entities
2. For each domain, queries EventStore for entities with >10 state changes in last 30 days
3. Filters through `event_normalizer.py` (excludes high-frequency sensor noise, filtered states)
4. Feeds active entities into pattern mining pipeline

### Layer 2 — Emergent Composites (`aria/iw/composite.py`)

When multiple BehavioralStates are frequently co-active:
1. After recording an observation, check: were any other states active in overlapping time windows?
2. Track co-activation counts in `state_co_activations` table
3. When co-activation count ≥ 5 AND co-activation rate ≥ 60%: propose composite candidate
4. Run discovery pipeline on *activation events* of child states to find consistent ordering (not just co-occurrence)
5. Use `co_occurrence.find_co_occurring_sets()` on state activations to cluster, preventing combinatorial explosion
6. Composite definition = `composite_of: (child_state_1_id, child_state_2_id, ...)`
7. Composite enters lifecycle at seed stage

**Guardrails:**
- Max 20 active composites (configurable via `iw.max_composites`, oldest/lowest-confidence pruned when exceeded)
- User can archive/promote on dashboard
- Rejected automations downweight source state via feedback loop

---

## Backtesting Engine (`aria/iw/backtest.py`)

Triggered at the emerging→confirmed lifecycle gate. **Required** — states cannot promote without passing.

### Three Test Types

**1. Historical Replay:**
- Load last 90 days from EventStore
- Replay events through a fresh detector instance with candidate definition
- Count: true activations (matched manual actions), false activations (no manual action), missed activations (manual action, no detection)
- Manual actions sourced from gap analyzer output as proxy ground truth
- Output: precision, recall, F1 score

**2. Holdout Validation:**
- Stratified temporal split by day_type (70% train / 30% test) — ensures proportional workday/weekend/holiday in both sets
- Discovery runs on train split, generates definition
- Replay test split, measure consistency
- Output: train_consistency, test_consistency, drift_score

**3. Counterfactual Test:**
- For each observation where expected_outcome was a manual action: generate HA automation YAML via Phase 3 template engine, simulate trigger/condition logic against historical events
- Count: would_have_automated correctly, would_have_been_wrong
- Output: automation_value_score (% of manual actions correctly covered)

### Pass Criteria (all required for emerging→confirmed)

| Test | Criterion | Rationale |
|------|-----------|-----------|
| Historical replay | F1 ≥ max(0.65, consistency - 0.10) | Adaptive threshold per state |
| Holdout validation | test_consistency within 20% of train_consistency | Temporal stability |
| Counterfactual | automation_value_score ≥ 0.50 | Worth automating |

---

## Synthetic Test Framework (`aria/iw/synthetic.py`)

### Type 1 — Simulated Event Streams (correctness)

```python
class EventSimulator:
    def inject_pattern(self,
        entities: list[str],
        sequence_delays: list[int],       # seconds between events
        repeat_count: int,
        consistency: float,               # 0-1, probability of pattern occurring each cycle
        timing_jitter_seconds: int = 300, # Gaussian stddev around mean timing
        noise_profile: str = "realistic", # random | periodic | bursty
        noise_events_per_cycle: int = 10,
        day_types: list[str] = ["workday"],
    ) -> list[dict]:
```

- Gaussian timing jitter around mean (real homes don't repeat at exact times)
- Three noise profiles: `random` (uniform), `periodic` (sensor-like updates), `bursty` (HVAC-like correlated noise)
- Events written to temporary SQLite database (not production EventStore)
- Known-answer tests: injected pattern at 80% consistency with 20 repeats → discovery should find at emerging stage

### Type 2 — Hyperparameter Sweeps (optimization)

```python
class HyperparameterSweep:
    def sweep(self,
        param_key: str,              # e.g. "iw.min_observations_emerging"
        values: list[Any],           # [5, 7, 10, 15]
        event_source: str,           # "synthetic" or "historical"
        quality_metric: str,         # "f1" | "precision" | "automation_value"
    ) -> list[dict]:
```

- Always includes current production config as baseline
- Reports improvement/regression relative to baseline
- CLI: `aria sweep --param iw.min_consistency_confirmed --values 0.60,0.65,0.70,0.75`
- Uses isolated SQLite + fresh detector (no production impact, CI-compatible)

---

## Configuration Entries

All new settings follow the Phase 2 layman/technical description pattern.

| Key | Default | Range | Description |
|-----|---------|-------|-------------|
| `iw.discovery_interval_hours` | 6 | 1-24 | How often discovery runs |
| `iw.min_discovery_confidence` | 0.60 | 0.3-0.95 | Minimum pattern confidence for chain construction |
| `iw.min_match_ratio` | 0.50 | 0.2-0.9 | Confirming indicator match ratio to record observation |
| `iw.min_observations_seed` | 3 | 1-10 | Observations to enter seed stage |
| `iw.min_observations_emerging` | 7 | 3-20 | Observations for seed→emerging |
| `iw.min_consistency_emerging` | 0.60 | 0.3-0.9 | Consistency for seed→emerging |
| `iw.min_observations_confirmed` | 15 | 7-50 | Observations for emerging→confirmed |
| `iw.min_consistency_confirmed` | 0.70 | 0.4-0.95 | Consistency for emerging→confirmed |
| `iw.min_observations_mature` | 30 | 15-100 | Observations for confirmed→mature (without user approval) |
| `iw.min_consistency_mature` | 0.80 | 0.5-0.98 | Consistency for confirmed→mature |
| `iw.min_density_emerging` | 0.3 | 0.1-1.0 | Min observations per active-day for emerging |
| `iw.min_density_confirmed` | 0.5 | 0.2-1.0 | Min observations per active-day for confirmed |
| `iw.dormant_days` | 30 | 7-90 | Days without observation before dormancy |
| `iw.retired_days` | 90 | 30-365 | Days dormant before retirement |
| `iw.max_composites` | 20 | 5-50 | Maximum active composite states |
| `iw.backtest_days` | 90 | 30-365 | Days of history for backtesting |
| `iw.backtest_holdout_ratio` | 0.30 | 0.15-0.40 | Holdout fraction for validation |
| `iw.backtest_min_f1` | 0.65 | 0.4-0.9 | Minimum F1 for backtest pass |
| `iw.detector_window_seconds` | 60 | 30-300 | Timer interval for ActiveState expiry check |
| `iw.cold_start_replay_minutes` | 60 | 15-180 | EventStore replay window on restart |

---

## New Files

| File | Purpose |
|------|---------|
| `aria/iw/__init__.py` | I&W package init |
| `aria/iw/models.py` | Indicator, BehavioralStateDefinition, BehavioralStateTracker, ActiveState |
| `aria/iw/discovery.py` | Batch discovery engine (patterns + gap → indicator chains) |
| `aria/iw/detector.py` | Real-time detector hub module (event subscriber + sliding window) |
| `aria/iw/lifecycle.py` | Lifecycle state machine (promotion/demotion/backtest gate) |
| `aria/iw/backtest.py` | Historical replay, holdout validation, counterfactual testing |
| `aria/iw/composite.py` | Emergent composite state detection |
| `aria/iw/synthetic.py` | Event simulator + hyperparameter sweep framework |

---

## Key Architectural Principles

1. **Definition is immutable, tracking is mutable.** Separating the pattern from its observations enables clean backtesting and prevents mutation during evaluation.
2. **Build on Phase 3, don't replace it.** Discovery consumes patterns.py + gap_analyzer output. Co_occurrence clusters feed composite detection. The automation generator handles YAML output.
3. **Entity-indexed O(1) lookup.** Real-time detector pre-indexes definitions by entity_id. Per-event cost is proportional to the number of definitions referencing that entity, not total definitions.
4. **Cold-start seeding.** On restart, replay recent EventStore through detector. No lost state (lesson #5).
5. **Domain filtering at subscriber.** Only subscribe to domains referenced in definitions (lesson #39).
6. **Backtest is a required gate.** No promotion to confirmed without passing backtesting. Prevents false pattern promotion.
7. **Adaptive thresholds.** F1 threshold adapts to the state's own consistency. Observation density prevents low-frequency patterns from gaming count thresholds.
8. **Graceful degradation.** Discovery runs without LLM. Real-time detection works without discovery (just uses existing definitions). Backtesting works without automation generator (skips counterfactual test).

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Discovery too slow on large EventStore | Limit to last 90 days, use existing indexed queries, patterns.py already handles this |
| Too many definitions overwhelming detector | Entity_index makes per-event cost O(definitions_per_entity), not O(total). Cap composites at 20. |
| Backtest false negatives blocking good patterns | Adaptive F1 threshold (consistency-based). Manual override to force-promote. |
| Composite explosion | Co_occurrence clustering limits candidates. Max 20 cap with LRU pruning. |
| Memory pressure from ActiveStates | ActiveStates are lightweight (few fields). Max concurrent ≈ number of definitions. |
| Temporal drift in patterns | Precondition timing recomputed from recent 30 days. Dormancy catches patterns that stop occurring. |
