# Phase 3: Automation Generator Rewrite — Design Document

**Date:** 2026-02-20
**Status:** Approved
**Parent:** `docs/plans/2026-02-20-aria-roadmap-2-design.md` (Roadmap 2.0)
**Depends on:** Phase 1 (EventStore + EntityGraph) ✅, Phase 2 (Unified ML + Presence Weights) ✅

---

## Vision

Transform ARIA's automation pipeline from a basic pattern→suggestion system into a
calendar-aware, event-stream-first automation generator that:

1. Detects behavioral sequences (not time slots) from EventStore
2. Identifies manual actions that could be automated (gap analysis)
3. Generates full HA-native YAML with validated triggers, conditions, and actions
4. Compares against existing HA automations (shadow comparison)
5. Polishes output via LLM with strict validation
6. Degrades gracefully at every layer

---

## Locked-In Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | EventStore (migrate patterns off logbook files) | Event-stream-first principle |
| Generator architecture | New module, orchestrator thinned to coordinator | Separation of concerns |
| LLM scope | Full refinement in Phase 3 (alias + description text only) | User requested |
| Shadow sync | Periodic cache (startup + every 30min) | Offline-capable, no API hammering |
| Detection philosophy | Behavioral sequences, not time slots | Roadmap principle #3 |
| Day-type segmentation | Workday/weekend/holiday/vacation/WFH analyzed separately | Calendar-aware accuracy |
| Manual vs automated | context_parent_id discrimination | Prevent circular suggestions |
| Module size target | <300-400 lines per file | Reusable segments |

---

## Complete Architecture Diagram

```
HA WebSocket (state_changed)
        │
        ▼
Activity Monitor (MODIFIED)
  ├── Extract context.parent_id from event context (NEW)
  └── Persist to EventStore with context_parent_id
        │
        ▼
EventStore (SQLite events.db)
  ├── context_parent_id TEXT column (NEW — Phase 3 migration)
  ├── Indexes: timestamp, entity_id, area_id, domain, context_parent_id
  └── 90-day retention with daily pruning
        │
        ▼
Event Normalizer Pipeline (NEW — aria/shared/)
  ├── 1. State filtering ─────────── Remove unavailable/unknown transitions
  ├── 2. Entity health filtering ── Exclude unreliable entities (<80% available)
  ├── 3. User exclusion filtering ─ Exclude entities/areas/domains/glob patterns
  ├── 4. Day classification ─────── Classify each day: workday/weekend/holiday/vacation/WFH
  ├── 5. Context filtering ──────── Tag automated vs manual (context_parent_id)
  ├── 6. State normalization ────── on/True/detected → "positive"; off/False/clear → "negative"
  ├── 7. Area-level aggregation ─── entity_id → (area_id, domain, action) via EntityGraph
  ├── 8. Day-type segmentation ──── Split events into workday/weekend/holiday pools
  ├── 9. Set co-occurrence ──────── Order-independent clustering within time windows
  ├── 10. Adaptive time windows ─── median ± 2σ per pattern (skip time condition if σ > 90min)
  └── 11. Environmental correlation  Pearson r with sun/illuminance → prefer sensor triggers
        │
   ┌────┴──────────────────────┐
   │                            │
   ▼                            ▼
Pattern Engine (REWRITTEN)    Gap Analyzer (NEW)
├── EventStore queries         ├── Manual-only events (context_parent_id IS NULL)
├── Per day-type analysis      ├── Frequent subsequences (PrefixSpan/GSP)
├── DTW clustering (preserved) ├── Cross-ref HA automation cache
├── Apriori association rules  ├── Sequence detection, not time bucketing
├── Periodic (every 2h)        ├── Periodic (every 4h)
├── Top-20 areas by activity   ├── Min 15 occurrences, 60% consistency
├── Memory budget: 512MB       ├── Min 14 days of data
└── → patterns cache           └── → gaps cache
   │    New fields:               │    Fields:
   │    entity_chain              │    entity_sequence
   │    trigger_entity            │    manual_count
   │    first_seen/last_seen      │    consistency
   │    source_event_count        │    missing_automation
   │    day_type                  │    suggested_trigger
   │                              │
   └───────────┬──────────────────┘
               │
               ▼
      Combined Scoring
      ┌──────────────────────────────────┐
      │ combined_score =                  │
      │   pattern_confidence * 0.5        │
      │ + gap_consistency * 0.3           │
      │ + recency_weight * 0.2            │
      │                                   │
      │ Filters:                          │
      │ - min_combined_score: 0.6         │
      │ - min_observations: 10            │
      │ - rejection penalty: 0.8x/reject  │
      │ - max 3 rejections → stop         │
      └──────────────────────────────────┘
               │
               ▼  Top-N (default 10 per cycle)
      AutomationGenerator (NEW — coordinator module)
               │
               ├──► Template Engine (aria/automation/template_engine.py)
               │    ├── DetectionResult → HA automation dict
               │    ├── Trigger Builder (domain-aware type selection)
               │    │   ├── binary_sensor → state trigger
               │    │   ├── sensor (numeric) → numeric_state trigger
               │    │   ├── person → zone trigger
               │    │   ├── sun → sun trigger
               │    │   ├── device_tracker → state trigger
               │    │   └── for duration = 5s debounce (not chain timing)
               │    ├── Condition Builder
               │    │   ├── Time condition (if >80% in 2h window, per day-type)
               │    │   ├── Weekday condition (from pattern day_type)
               │    │   ├── Holiday exclusion (if HA calendar entity available)
               │    │   ├── Presence condition (if correlated with person.*)
               │    │   ├── Illuminance condition (if sensor in same area)
               │    │   ├── State guard (skip if already in desired state)
               │    │   └── Safety defaults (presence for lights, quiet hours for notify)
               │    ├── Action Builder
               │    │   ├── Area targeting preferred over entity lists
               │    │   ├── Attribute extraction from EventStore (brightness, temp)
               │    │   ├── RESTRICTED_DOMAINS: lock, alarm, cover → approval required
               │    │   └── Service selection: domain-aware (light.turn_on, switch.turn_on)
               │    └── Mode Selection
               │         ├── Actions with delay/wait → restart
               │         ├── Notification actions → queued
               │         ├── Default → single + max_exceeded: silent
               │         └── Multi-room scene → parallel
               │
               ├──► LLM Refiner (aria/automation/llm_refiner.py)
               │    ├── Ollama model: llm.automation_model (default qwen2.5-coder:14b)
               │    ├── CAN change: alias, description
               │    ├── CANNOT change: triggers, conditions, actions, mode, id
               │    ├── Timeout: 30s → fallback to template output
               │    ├── Queue: submits through ollama-queue if enabled
               │    └── Post-refinement: string diff on non-text fields (reject structural changes)
               │
               └──► Validator (aria/automation/validator.py)
                    9-check validation suite:
                    ├── 1. yaml_parseable — valid YAML
                    ├── 2. required_fields — id, alias, triggers, actions present
                    ├── 3. state_values_quoted — on/off/yes/no are strings, not booleans
                    ├── 4. entities_exist — all entity_ids in EntityGraph
                    ├── 5. services_valid — all action services are known HA services
                    ├── 6. no_circular_trigger — action entities ≠ trigger entities
                    ├── 7. no_duplicate_id — unique across suggestions + HA cache
                    ├── 8. mode_appropriate — mode matches action type
                    └── 9. restricted_domain_check — lock/alarm/cover flagged
               │
               ▼
      HA Automation Sync (NEW)              Shadow Comparison (NEW)
      ├── Startup + every 30min       ──►   ├── Duplicate Detection
      ├── GET /api/config/automation/        │   ├── Exact match → suppress
      │   config                             │   ├── Superset (ARIA covers more) → flag "expands"
      ├── Incremental (hash per               │   └── Subset (existing covers more) → suppress
      │   automation, only re-normalize      ├── Conflict Detection
      │   changed ones)                      │   ├── Opposite action (turn_on vs turn_off)
      ├── Normalize: entity_id as list,      │   └── Parameter conflict (brightness 30% vs 100%)
      │   target areas resolved              ├── Gap Detection
      ├── Track enabled/disabled state       │   ├── Cross-area: "you have bedroom, not hallway"
      └── → ha_automations cache             │   └── Gap fills get +0.1 confidence boost
           │                                 ├── Disabled Automation Handling
           │                                 │   ├── Disabled ≠ duplicate
           │                                 │   └── Present as "improved version of disabled [name]"
           │                                 └── → annotated ShadowResult per candidate
           │                                        │
           └────────────────────────────────────────┘
                                                    │
                                                    ▼
                                           Orchestrator (THINNED)
                                           ├── Coordinates: detect → generate → shadow → store
                                           ├── Stores in automation_suggestions cache
                                           ├── Approval flow:
                                           │   ├── → HA REST API (create automation)
                                           │   ├── → Immediate ha_automations cache update
                                           │   ├── → Pattern gets user_validated: true
                                           │   └── → Publishes automation_approved event
                                           ├── Rejection flow:
                                           │   ├── → 0.8x confidence penalty on source pattern
                                           │   ├── → After 3 rejections: stop suggesting
                                           │   └── → Publishes automation_rejected event
                                           ├── Rollback:
                                           │   ├── → HA REST API delete (aria-tagged automations)
                                           │   └── → Remove from ha_automations cache
                                           └── Health:
                                               └── → automation_system_health cache
                                                    │
                                             ┌──────┴──────────┐
                                             ▼                  ▼
                                       Dashboard (Decide)    CLI Commands
                                       ├── Status badges:    aria patterns
                                       │   NEW / CONFLICT    aria gaps
                                       │   / GAP FILL        aria suggest
                                       ├── Conflict          aria shadow
                                       │   warnings          aria shadow sync
                                       ├── Gap fill labels   aria rollback --last
                                       ├── Undo button
                                       │   (24h window)
                                       ├── Health status bar
                                       ├── "Show X
                                       │   suppressed" toggle
                                       └── Settings:
                                           Data Filtering
                                           (area/domain/entity
                                           toggles)
```

---

## Testing Data Flow Diagram

```
Test Fixtures (synthetic data)
        │
        ├── Synthetic Events Generator
        │   ├── Known patterns: "bedroom motion → light on" (45 of 60 workdays)
        │   ├── Known gaps: "kitchen light manual on" (40 of 60 workdays, no automation)
        │   ├── Noise: random sensor fluctuations, unavailable transitions
        │   ├── Holiday behavior: 4 days with weekend-like patterns on weekdays
        │   ├── Vacation days: 5 days with no person home
        │   ├── Automated events: context_parent_id set for automation-triggered changes
        │   └── Seasonal variation: earlier light-on in winter days
        │
        ├── Mock HA Automations (for shadow comparison)
        │   ├── Existing: "bedroom motion → bedroom lamp" (to test duplicate)
        │   ├── Existing: "kitchen motion → kitchen light OFF at night" (to test conflict)
        │   ├── Disabled: "hallway motion → hallway light" (to test disabled handling)
        │   └── Missing: no hallway automation (to test gap detection)
        │
        ├── Mock EntityGraph
        │   ├── 5 areas: bedroom, kitchen, hallway, living_room, bathroom
        │   ├── 3-4 entities per area (motion, light, door, illuminance)
        │   └── Device→area mapping for resolution testing
        │
        └── Mock Calendar
            ├── 4 holiday events (Christmas, New Year, etc.)
            ├── 5 vacation days (context_parent_id NULL but person not_home)
            └── 3 WFH days (person home all day on weekday)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1: Unit Tests (per component, mocked dependencies)        │
│                                                                  │
│  test_event_normalizer.py                                        │
│  ├── State filtering: assert unavailable/unknown events removed  │
│  ├── Entity health: assert <80% available entities excluded      │
│  ├── User exclusion: assert excluded entities/areas/domains gone │
│  ├── Day classification: assert holidays/vacation correctly      │
│  │   classified from mock calendar                               │
│  ├── Context filtering: assert automated events tagged           │
│  ├── State normalization: on/True/detected all → "positive"      │
│  ├── Area aggregation: entity events grouped by area+domain      │
│  ├── Co-occurrence: assert order-independent set detection        │
│  ├── Adaptive windows: assert median ± 2σ calculation            │
│  └── Environmental correlation: assert sun/illuminance preferred │
│                                                                  │
│  test_automation_generator.py                                    │
│  ├── Trigger builder: domain → correct HA trigger type           │
│  ├── Condition builder: time, weekday, presence, illuminance     │
│  ├── Action builder: area targeting, attribute extraction         │
│  ├── Safety conditions: defaults injected per action domain      │
│  ├── Mode selection: delay→restart, notify→queued, default→single│
│  ├── YAML quoting: on/off/yes/no always quoted as strings        │
│  └── Restricted domains: lock/alarm/cover flagged                │
│                                                                  │
│  test_anomaly_gap.py                                             │
│  ├── Sequence detection: frequent subsequences found             │
│  ├── Manual-only: automated events excluded from gap counting    │
│  ├── Cross-ref: existing automations not flagged as gaps         │
│  ├── Consistency calculation: correct ratio computation          │
│  └── Minimum thresholds: below min_occurrences returns empty     │
│                                                                  │
│  test_shadow_comparison.py                                       │
│  ├── Exact duplicate: same trigger+action → suppress             │
│  ├── Superset: ARIA area target ⊃ existing entity → flag expand  │
│  ├── Subset: existing covers more → suppress                     │
│  ├── Conflict: opposite action detected                          │
│  ├── Parameter conflict: same service, different brightness      │
│  ├── Gap detection: cross-area suggestion                        │
│  ├── Disabled automation: not treated as duplicate               │
│  └── Confidence boost: gap fill gets +0.1                        │
│                                                                  │
│  test_automation_validator.py                                    │
│  ├── Valid YAML passes all 9 checks                              │
│  ├── Unquoted boolean state caught                               │
│  ├── Missing required field caught                               │
│  ├── Invalid service name caught                                 │
│  ├── Circular trigger caught (action entity = trigger entity)    │
│  ├── Duplicate ID caught                                         │
│  └── Restricted domain flagged                                   │
│                                                                  │
│  test_llm_refiner.py                                             │
│  ├── Text-only changes accepted (alias, description)             │
│  ├── Structural changes rejected (trigger/action modified)       │
│  ├── Timeout → fallback to template output                       │
│  └── Ollama unavailable → fallback to template output            │
│                                                                  │
│  test_day_classifier.py                                          │
│  ├── Weekday correctly classified as workday                     │
│  ├── Saturday/Sunday classified as weekend                       │
│  ├── Holiday keyword match → holiday                             │
│  ├── Multi-day event with vacation keyword → vacation            │
│  ├── WFH keyword → wfh (if >5 days in window)                   │
│  └── No calendar → all weekdays = workday, weekends = weekend    │
│                                                                  │
│  test_entity_health.py                                           │
│  ├── 95%+ available → healthy (full weight)                      │
│  ├── 80-95% → flaky (0.5x weight)                               │
│  ├── <80% → unreliable (excluded)                                │
│  └── Custom threshold respected                                  │
│                                                                  │
│  test_ha_automation_sync.py                                      │
│  ├── Full sync on empty cache                                    │
│  ├── Incremental: only changed automations re-normalized         │
│  ├── Deleted automation removed from cache                       │
│  ├── Normalization: entity_id string → list, area resolved       │
│  └── Enabled/disabled flag preserved                             │
│                                                                  │
│  test_calendar_context.py                                        │
│  ├── Google Calendar fetch (mock gog CLI)                        │
│  ├── HA calendar entity fetch (mock API)                         │
│  ├── Keyword matching for holiday/vacation/WFH                   │
│  └── Graceful degradation: no calendar → weekday/weekend only    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 2: Integration Tests (multi-component, mock HA)           │
│                                                                  │
│  test_automation_pipeline.py                                     │
│  ├── Full pipeline: insert synthetic events into real EventStore │
│  │   → run normalizer → pattern detection + gap analysis         │
│  │   → generator → shadow comparison → assert suggestions in     │
│  │   cache with correct status badges                            │
│  ├── Known-answer: predefined event sequences with known         │
│  │   patterns → assert specific automations generated            │
│  │   (golden file approach in tests/integration/known_answer/)   │
│  ├── Cold start: empty EventStore → all engines return gracefully│
│  │   with "Insufficient data" status, no crashes                 │
│  ├── Rejection feedback: generate → reject → re-run → assert     │
│  │   confidence penalty applied, suppressed after 3              │
│  ├── Approval feedback: generate → approve → assert              │
│  │   ha_automations cache updated immediately                    │
│  ├── Calendar integration: holiday events → workday patterns     │
│  │   exclude holiday data, weekend patterns include it           │
│  └── Day-type separation: workday morning at 6:30 and weekend   │
│       morning at 9:00 detected as TWO distinct patterns          │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 3: Validation Tests (HA schema compliance)                │
│                                                                  │
│  test_ha_yaml_compliance.py                                      │
│  ├── Every generated automation parseable as valid YAML          │
│  ├── State quoting matrix: every domain × state combination      │
│  │   → assert boolean-like states always quoted                  │
│  ├── Entity reference integrity: every entity_id exists in       │
│  │   mock EntityGraph                                            │
│  ├── Round-trip: generate → serialize → deserialize → compare    │
│  │   dicts (no data loss in serialization)                       │
│  ├── Required HA fields: id, alias, triggers, actions present    │
│  └── Mode field valid: single/restart/queued/parallel only       │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 4: Performance Tests                                       │
│                                                                  │
│  test_performance.py                                             │
│  ├── Large EventStore: 100,000 synthetic events → pattern        │
│  │   detection completes in <30s, memory < 512MB                 │
│  ├── Incremental sync: 200 HA automations, change 5 → only 5    │
│  │   re-normalized                                               │
│  └── Top-N cap: 80 detections → only 10 go through template +   │
│       LLM, rest queued for next cycle                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Event Normalizer Pipeline

Sits between EventStore and detection engines. Produces clean, filtered, normalized
events segmented by day type.

**State Equivalence Map:**

```python
STATE_EQUIVALENCE = {
    "binary_sensor": {
        "positive": {"on", "True", "detected", "open", "unlocked", "home"},
        "negative": {"off", "False", "clear", "closed", "locked", "not_home"},
    },
}
```

Detection engines work with `"positive"` / `"negative"`. YAML generator maps back
to actual entity state values when building triggers.

**Entity Health Grading:**

| Grade | Availability | Detection Behavior |
|-------|-------------|-------------------|
| healthy | >95% | Full weight |
| flaky | 80-95% | 0.5x confidence weight |
| unreliable | <80% | Excluded entirely |

Computed from EventStore: count `unavailable` transitions vs total events per entity.

### 2. Day Classifier + Calendar Context

Classifies each day in the analysis window before detection engines run.

```python
@dataclass
class DayContext:
    date: str
    day_type: Literal["workday", "weekend", "holiday", "vacation", "wfh"]
    calendar_events: list[str]
    away_all_day: bool
```

**Data sources:**
- Weekday/weekend: from date
- Holiday: public holiday calendar entity OR keyword match in Google Calendar
- Vacation: multi-day events with vacation keywords, or person not_home >24h
- WFH: person home all day on weekday, or calendar keyword match

**Day-type segmentation rules:**
- Workday and weekend patterns analyzed separately
- Holidays merge with weekends (too few for independent analysis in 90 days)
- Vacation days excluded entirely (empty-house noise)
- WFH days: separate pool if >5 in window, else merge with workdays
- Minimum days per type still applies (7+ required)

**Graceful degradation:** No calendar configured → weekday/weekend only. No holiday
calendar → holidays detected by behavior anomaly (weekday with weekend-like pattern).

### 3. Pattern Engine (Rewrite)

Same algorithms (DTW clustering, Apriori association rules), new data source and output.

**Changes from current:**

| Aspect | Current | Phase 3 |
|--------|---------|---------|
| Data source | `~/ha-logs/` logbook JSON | EventStore queries |
| Entity resolution | Area from filenames | EntityGraph.get_area() |
| Scheduling | One-shot on init | Periodic (every 2h, configurable) |
| Day awareness | None | Per day-type analysis |
| Output | Basic pattern schema | + entity_chain, trigger_entity, first_seen, last_seen, source_event_count, day_type |

**Performance guards:**
- Top-20 most active areas only (configurable: `patterns.max_areas`)
- Memory budget: 512MB hard ceiling
- Batch window: 7-day sliding windows, merge patterns across windows
- Sampling for areas with >50,000 events

### 4. Anomaly-Gap Analyzer (New)

Detects repetitive manual actions that could be automated. Uses **sequence mining**,
not time bucketing.

**Algorithm:**
1. Query EventStore for manual-only events (`context_parent_id IS NULL`)
2. For each event, look backward for preceding events within configurable window
3. Build frequent subsequences using PrefixSpan or GSP
4. Count sequence occurrences, compute consistency (occurrences / eligible days)
5. Cross-reference against `ha_automations` cache — is the final action automated?
6. Output gaps with confidence, frequency, suggested automation type

**Key distinction from Pattern Engine:**
- Pattern Engine detects ALL recurring sequences (including automated ones) for understanding household rhythms
- Gap Analyzer detects MANUAL-ONLY sequences to find automation opportunities

### 5. Automation Generator (New Module — Coordinator)

Coordinates: combined scoring → template engine → LLM refinement → validation.

**Combined Scoring:**

```
combined_score = pattern_confidence * 0.5 + gap_consistency * 0.3 + recency_weight * 0.2
recency_weight = min(1.0, events_in_last_14d / total_events)
```

**Filters before generation:**
- `min_combined_score: 0.6`
- `min_observations: 10`
- Rejection penalty: `0.8x` per prior rejection from same pattern
- Max 3 rejections → stop suggesting from that pattern
- Top-N cap: `max_suggestions_per_cycle: 10`

### 6. Template Engine (aria/automation/)

**DetectionResult** — unified input from both engines:

```python
@dataclass
class DetectionResult:
    source: Literal["pattern", "gap"]
    trigger_entity: str
    action_entities: list[str]
    entity_chain: list[ChainLink]
    area_id: str | None
    confidence: float
    recency_weight: float
    observation_count: int
    first_seen: str
    last_seen: str
    day_type: str
    combined_score: float
```

**Multi-step chain handling (Option A):**
Only automate the LAST link in a chain. Earlier links become conditions, not triggers.
Example: bedroom_motion → bathroom_motion → kitchen_light ON
- Trigger: kitchen_motion (most common first-entity in the final-action context)
- Condition: bedroom_motion detected in last 20min (from chain timing)
- Action: kitchen light turn_on

The chain gives high confidence; intermediate events give conditions.

**Trigger type selection** — domain-aware:

| Domain | HA Trigger Type |
|--------|----------------|
| binary_sensor (motion, door) | state |
| sensor (numeric) | numeric_state |
| person | zone |
| sun | sun |
| device_tracker | state |
| input_boolean, switch | state |

`for` duration = 5s debounce default (configurable per domain), not chain timing.

**Condition builder** — additive:
- Time: only if >80% of observations in 2h window (per day-type)
- Weekday: from pattern day_type (workday → [mon-fri], weekend → [sat-sun])
- Holiday exclusion: template condition on calendar entity if available
- Presence: if correlated with person.* state
- Illuminance: if sensor in same area and action is light
- State guard: skip if entity already in desired state
- Safety defaults per action domain (see below)

**Safety conditions** — injected unless overridden:

```python
SAFETY_CONDITIONS = {
    "light.turn_on": [
        ("presence", "person.* == home"),
        ("illuminance", "sensor.*_illuminance < 50"),
    ],
    "notify.*": [
        ("quiet_hours", "time NOT between 23:00-07:00"),
    ],
    "climate.*": [
        ("presence", "person.* == home"),
    ],
}
```

Pattern data can override: if the user turns on lights at midday consistently,
skip illuminance condition.

**Mode selection** — action-aware:

| Scenario | Mode | Why |
|----------|------|-----|
| Actions with delay/wait | restart | New trigger resets timer |
| Notification actions | queued | Don't drop events |
| Multi-room scene | parallel | Independent rooms |
| Default | single + max_exceeded: silent | Prevent log spam |

**YAML value safety:**
- All state values in `["on", "off", "yes", "no", "true", "false"]` force-quoted as strings
- Custom YAML representer or post-serialization string replacement

**Description template** (pre-LLM):

```
ARIA detected: [trigger] triggers [action] [confidence]% of [day_type]
[time window if applicable]. [observation_count] observations over
[date range]. Source: [engine] (confidence: [x], recency: [y]).
To dismiss: reject on the ARIA dashboard. ARIA stops suggesting
after 3 rejections.
```

### 7. LLM Refiner

**Contract:**
- CAN change: `alias`, `description`
- CANNOT change: `triggers`, `conditions`, `actions`, `mode`, `id`
- Validation: YAML parse + string diff on all non-text fields → reject if structural change
- Model: `llm.automation_model` (default: `qwen2.5-coder:14b`)
- Timeout: 30s → fallback to template output
- Queue: through `ollama-queue` if `llm.queue_enabled`
- Ollama unavailable → template ships as-is

### 8. Validator (9 Checks)

| # | Check | Catches |
|---|-------|---------|
| 1 | yaml_parseable | Invalid YAML syntax |
| 2 | required_fields | Missing id, alias, triggers, actions |
| 3 | state_values_quoted | `on`/`off` as booleans instead of strings |
| 4 | entities_exist | References to removed/unknown entities |
| 5 | services_valid | Typos in service names |
| 6 | no_circular_trigger | Action entity = trigger entity (infinite loop) |
| 7 | no_duplicate_id | ID collision with other suggestions or HA cache |
| 8 | mode_appropriate | Mode doesn't match action type |
| 9 | restricted_domain_check | lock/alarm/cover without approval flag |

**Live entity validation:** Before presenting suggestions, query `GET /api/states` for
referenced entities. If any return `unavailable` for >24h, flag suggestion as degraded.

### 9. Shadow Comparison

**Duplicate detection** — three relationship types:

| Relationship | Criteria | Action |
|-------------|----------|--------|
| Exact duplicate | Same trigger + same targets | Suppress |
| Superset | Same trigger, ARIA targets ⊃ existing | Flag: "Expands on [name]" |
| Subset | Same trigger, ARIA targets ⊂ existing | Suppress |

Uses EntityGraph to resolve `area: bedroom` → entity list for set comparison.

**Conflict detection** — two types:
- Opposite action: same trigger entity/state, opposite service (turn_on vs turn_off)
- Parameter conflict: same trigger+target+service, different data values (brightness 30% vs 100%, flagged if difference >20%)

**Gap detection:**
- Cross-area: existing automation for bedroom but not hallway → gap fill (+0.1 boost)
- Disabled automations: NOT treated as duplicates. If ARIA's version has higher confidence, present as "Improved version of your disabled [name]"

**Incremental sync:**
- Hash each raw HA automation response
- Only re-normalize changed/new automations
- Track changes: "User modified [name] since last sync" — useful feedback signal

**Immediate cache update on approval:** When orchestrator creates an automation in HA,
add to `ha_automations` cache immediately (don't wait 30min sync). Prevents re-suggestion.

### 10. Feedback Loop

| Event | Effect |
|-------|--------|
| User approves suggestion | Pattern gets `user_validated: true`, immediate cache update |
| User rejects suggestion | 0.8x confidence penalty, stop after 3 rejections |
| ARIA automation fires in HA | Positive reinforcement (trace count > 0) |
| ARIA automation never fires (14 days) | Flag "Unused — consider removing" |
| User edits ARIA automation | Record diff → detect systematic template bias |
| User deletes ARIA automation | Remove from cache, downweight source pattern |

### 11. Observability

New cache category `automation_system_health`:

```python
{
    "pattern_engine": {
        "last_run": "...", "status": "healthy",
        "patterns_found": 23, "events_analyzed": 45000,
        "duration_seconds": 12,
    },
    "gap_analyzer": {
        "last_run": "...", "status": "healthy",
        "gaps_found": 8, "manual_events_counted": 12000,
    },
    "shadow_sync": {
        "last_sync": "...", "ha_automations_count": 45,
        "aria_automations_count": 3, "changes_since_last": 1,
    },
    "suggestions": {
        "pending": 5, "approved": 3,
        "rejected": 2, "suppressed_duplicates": 12,
    },
}
```

### 12. Rollback

- ARIA-created automations tagged in description with identifiable marker
- `DELETE /api/automations/{suggestion_id}` → HA REST API remove
- Dashboard "Undo" button (24h window)
- CLI: `aria rollback --last`

---

## EventStore Schema Migration

```sql
ALTER TABLE events ADD COLUMN context_parent_id TEXT;
CREATE INDEX idx_events_context ON events(context_parent_id);
```

Existing rows get `context_parent_id = NULL` (treated as manual — conservative default).

---

## File Layout

### New Files

```
aria/automation/                           # NEW package — reusable YAML generation
  ├── __init__.py                    ~10
  ├── models.py                      ~100   DetectionResult, ShadowResult, DayContext, etc.
  ├── template_engine.py             ~300   DetectionResult → HA automation dict (coordinator)
  ├── trigger_builder.py             ~200   Domain-aware trigger type selection
  ├── condition_builder.py           ~250   Presence, illuminance, time, weekday, safety
  ├── action_builder.py              ~200   Area targeting, attributes, restricted domains
  ├── llm_refiner.py                 ~200   Ollama polish + fallback
  └── validator.py                   ~250   9-check validation suite

aria/shared/
  ├── event_normalizer.py            ~200   Pipeline orchestrator + state filtering
  ├── day_classifier.py              ~200   Calendar integration + day type segmentation
  ├── co_occurrence.py               ~200   Set co-occurrence + adaptive time windows
  ├── environmental_correlator.py    ~150   Sun/illuminance Pearson correlation
  ├── ha_automation_sync.py          ~200   Periodic HA fetch + incremental hash cache
  ├── shadow_comparison.py           ~300   Duplicate/conflict/gap/superset detection
  ├── calendar_context.py            ~200   Google Calendar + HA calendar entity fetch
  └── entity_health.py               ~150   Availability % scoring + health grading

aria/modules/
  ├── automation_generator.py        ~300   Coordinator module (detect → score → generate → shadow)
  └── anomaly_gap.py                 ~300   Sequence mining from EventStore (manual-only)
```

### Modified Files

```
aria/modules/patterns.py             REWRITE  EventStore data source, periodic scheduling,
                                              day-type analysis, new output fields
aria/modules/orchestrator.py         THIN     Remove _pattern_to_suggestion(), delegate to
                                              AutomationGenerator. Keep approval/rejection/HA API.
                                              Add immediate cache update on approval.
aria/shared/event_store.py           MIGRATE  Add context_parent_id column + index
aria/modules/activity_monitor.py     MODIFY   Extract context.parent_id, pass to EventStore
aria/hub/core.py                     MODIFY   Register new modules, wire sync timer
aria/hub/routes.py                   MODIFY   New API endpoints (shadow/*, automations/*)
aria/dashboard/spa/src/pages/
  Decide.jsx                         MODIFY   Status badges, conflict warnings, undo, health
aria/dashboard/spa/src/pages/
  intelligence/Settings.jsx          MODIFY   Data Filtering section
config_defaults.py                   MODIFY   Add ~28 new config entries with descriptions
aria/engine/llm/
  automation_suggestions.py          DELETE   Dead code replaced by AutomationGenerator
```

### New Test Files

```
tests/hub/test_automation_generator.py    ~400
tests/hub/test_anomaly_gap.py             ~300
tests/hub/test_shadow_comparison.py       ~400
tests/hub/test_event_normalizer.py        ~350
tests/hub/test_ha_automation_sync.py      ~200
tests/hub/test_automation_validator.py    ~300
tests/hub/test_day_classifier.py          ~200
tests/hub/test_entity_health.py           ~150
tests/hub/test_calendar_context.py        ~200
tests/hub/test_llm_refiner.py            ~200
tests/hub/test_trigger_builder.py         ~200
tests/hub/test_condition_builder.py       ~250
tests/hub/test_action_builder.py          ~200
tests/integration/
  test_automation_pipeline.py             ~300
tests/integration/known_answer/
  test_automation_golden.py               ~200
```

---

## New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/shadow/sync` | POST | Force HA automation re-sync |
| `/api/shadow/status` | GET | Last sync time, automation count, health |
| `/api/shadow/compare` | GET | Current comparison results |
| `/api/automations/health` | GET | System health (pattern engine, gap, shadow, suggestions) |
| `/api/automations/{id}` | DELETE | Remove ARIA-created automation from HA + cache |

---

## New CLI Commands

```bash
aria patterns          # Show detected patterns (top 10 by confidence)
aria gaps              # Show detected automation gaps
aria suggest           # Force a suggestion generation cycle
aria shadow            # Show shadow comparison status
aria shadow sync       # Force HA automation re-sync
aria rollback --last   # Remove most recently ARIA-created automation
```

---

## Complete Config Entry Table

All entries include `description_layman` and `description_technical` per Phase 2 UX pattern.

### Pattern Engine

| Key | Default | Layman |
|-----|---------|--------|
| `patterns.analysis_interval` | 7200 | How often ARIA looks for new patterns (seconds) |
| `patterns.max_areas` | 20 | Maximum rooms to analyze at once |
| `patterns.memory_budget_mb` | 512 | Memory limit for pattern analysis |
| `patterns.min_events` | 500 | Minimum events before pattern analysis starts |
| `patterns.min_days` | 7 | Minimum days of data before pattern analysis |

### Gap Analyzer

| Key | Default | Layman |
|-----|---------|--------|
| `gap.analysis_interval` | 14400 | How often ARIA checks for things you do manually |
| `gap.min_occurrences` | 15 | Times you must do something before ARIA suggests automating |
| `gap.min_consistency` | 0.6 | How consistent the action must be (60% = most of the time) |
| `gap.min_days` | 14 | Minimum days of data before gap analysis |

### Automation Generator

| Key | Default | Layman |
|-----|---------|--------|
| `automation.max_suggestions_per_cycle` | 10 | Maximum new suggestions per analysis cycle |
| `automation.min_combined_score` | 0.6 | Minimum confidence before ARIA suggests anything |
| `automation.min_observations` | 10 | Minimum observations before suggesting |
| `automation.rejection_penalty` | 0.8 | How much confidence drops per rejection |
| `automation.max_rejections` | 3 | Stop suggesting after this many rejections |

### Shadow Comparison

| Key | Default | Layman |
|-----|---------|--------|
| `shadow.sync_interval` | 1800 | How often ARIA checks your existing automations |
| `shadow.duplicate_threshold` | 0.8 | How similar before ARIA considers it a duplicate |

### LLM Refinement

| Key | Default | Layman |
|-----|---------|--------|
| `llm.automation_model` | qwen2.5-coder:14b | AI model that polishes automation names/descriptions |
| `llm.automation_timeout` | 30 | Seconds to wait for AI polish before using template |

### Data Filtering

| Key | Default | Layman |
|-----|---------|--------|
| `filter.ignored_states` | ["unavailable", "unknown"] | State values excluded from analysis |
| `filter.min_availability_pct` | 80 | Devices below this % are ignored as unreliable |
| `filter.exclude_entities` | [] | Specific devices to exclude |
| `filter.exclude_areas` | [] | Rooms to exclude from suggestions |
| `filter.exclude_domains` | ["update", "button", "number", "input_number", "input_boolean", "input_select", "input_text", "persistent_notification", "scene", "script", "automation"] | Device types ARIA ignores |
| `filter.include_domains` | [] | If set, ONLY these types analyzed (whitelist mode) |
| `filter.exclude_entity_patterns` | ["*_battery", "*_signal_strength", "*_linkquality", "*_firmware"] | Name patterns to exclude |
| `filter.flaky_weight` | 0.5 | Confidence multiplier for unreliable devices |

### Calendar

| Key | Default | Layman |
|-----|---------|--------|
| `calendar.enabled` | true | Use your calendar to improve automation accuracy |
| `calendar.holiday_keywords` | ["holiday", "vacation", "PTO", "trip", "out of office", "off"] | Words that mean you're not working |
| `calendar.wfh_keywords` | ["WFH", "remote", "work from home"] | Words that mean you're working from home |
| `calendar.source` | google | Which calendar to check |
| `calendar.entity_id` | "" | HA calendar entity ID (if using HA calendar) |

### Normalizer

| Key | Default | Layman |
|-----|---------|--------|
| `normalizer.environmental_correlation_threshold` | 0.7 | How strongly time must correlate with light/sun to prefer sensor trigger |
| `normalizer.adaptive_window_max_sigma` | 90 | If timing varies more than this many minutes, skip time condition |

---

## Backward Compatibility

- Patterns cache: new fields are additive. Old consumers ignore unknown fields.
- `automation_suggestions` cache: add `schema_version: 2` field. Old entries preserved.
- Existing orchestrator approval/rejection API unchanged.
- Dashboard: new UI elements hidden gracefully if data not present.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| EventStore query performance on millions of rows | Tiered queries: area summary → top-N → sampling → batch windows |
| LLM structural changes bypass validation | String diff on non-text fields, not just YAML parse |
| Circular suggestions (automating automated actions) | context_parent_id discrimination + exclude automation domain |
| Trust erosion from bad suggestions | Min score threshold, rejection penalty, max rejections cap |
| Holiday/vacation pattern corruption | Day-type segmentation, vacation exclusion |
| Entity replacement splitting history | Area-level aggregation as primary detection unit |
| State value YAML corruption (on → true) | Force-quoting safety list + validation check #3 |
| Sync gap re-suggestion | Immediate cache update on approval |
| Memory exhaustion during pattern detection | Hard budget ceiling + batch windows + sampling |
| Calendar unavailable | Graceful degradation to weekday/weekend only |

---

## Key Architectural Principles (Phase 3 specific)

1. **Behavioral sequences, not time slots.** Detect causal chains. Time is a condition, not a trigger.
2. **Manual vs automated discrimination.** context_parent_id prevents circular suggestions.
3. **Calendar-aware segmentation.** Workday ≠ weekend ≠ holiday. Analyze separately.
4. **Normalize before detecting.** Clean data in → accurate patterns out.
5. **Combined scoring across engines.** Patterns + gaps + recency = one ranked list.
6. **LLM translates, template decides.** LLM polishes text. Template controls structure.
7. **Validate exhaustively.** 9 checks. Every boolean quoted. Every entity verified.
8. **Shadow before suggesting.** Never suggest what already exists.
9. **Feedback closes the loop.** Approvals boost, rejections penalize, edits inform.
10. **Small modules, reusable segments.** Every file <400 lines, every component testable in isolation.
