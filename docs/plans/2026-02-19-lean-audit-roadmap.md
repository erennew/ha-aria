# ARIA Lean Audit — Strategy Roadmap

**Date:** 2026-02-19
**Status:** Active
**Parent design:** `2026-02-19-lean-audit-restructure-design.md`

## Purpose

ARIA exists to produce two outputs:
1. **Automation recommendations** — pattern-based predictions of what to automate
2. **Anomaly detection** — deviations from learned baselines

This roadmap tracks the 5-phase engineering process to achieve those outputs reliably with minimal complexity.

---

## Phase Summary

| Phase | Name | Status | Deliverable |
|-------|------|--------|-------------|
| **1** | Module Triage | **Done** | 14 → 10 modules, 4 archived, 1 merged, 1 renamed |
| **2** | Known-Answer Test Harness | **Planned** | 11 known-answer tests + golden snapshots |
| **3** | Issue Triage & GitHub Roadmap | Queued | GitHub project board with milestones |
| **4** | Fix & Optimize | Queued | Security, reliability, performance fixes |
| **5** | UI — Decision Tool | Queued | OODA-based dashboard redesign |

---

## Phase 1: Module Triage (Done)

**Completed:** 2026-02-19
**Report:** `2026-02-19-module-triage-report.md`
**Branch:** `feature/lean-audit-phase1` (merged to main)

### Results

| Metric | Before | After |
|--------|--------|-------|
| Hub modules | 14 | 10 |
| Tests | 1,668 | 1,416 |
| Pipeline Sankey nodes | 31 | 25 |

### Decisions Made

- **Archived 4 modules:** online_learner (marginal value), organic_discovery (not feeding outputs), transfer_engine (future feature), activity_labeler (labels don't feed outputs)
- **Merged 1:** data_quality → discovery (entity classification now runs inside discovery)
- **Renamed 1:** pattern_recognition → trajectory_classifier (clarity, avoids collision with patterns.py)
- **Kept 8 as-is:** discovery, patterns, orchestrator, shadow_engine, ml_engine, intelligence, activity_monitor, presence
- **Architecture docs updated:** system-routing-map.md, architecture-detailed.md, pipelineGraph.js

### Surviving Module Inventory (10)

| Module | Role | Feeds |
|--------|------|-------|
| discovery | Entity/device/area scanning + classification | Foundation data |
| activity_monitor | Real-time state_changed listener | Feeds patterns + shadow |
| patterns | Recurring sequence detection (clustering + association rules) | Recommendations |
| orchestrator | Automation YAML suggestions from patterns | **Primary recommendation output** |
| shadow_engine | Predict-compare-score loop | **Primary anomaly output** |
| trajectory_classifier | Trajectory classification + anomaly explanation (Tier 3+) | Anomaly explanation |
| ml_engine | Model training, ensemble weights | Both |
| intelligence | Engine output → hub cache bridge | Both (bridge) |
| presence | MQTT/Frigate person tracking | Context signal |
| audit_logger | Tamper-evident audit trail | Cross-cutting |

---

## Phase 2: Known-Answer Test Harness (Current)

**Plan:** `2026-02-19-known-answer-test-harness.md`
**Design:** `2026-02-19-known-answer-test-harness-design.md`
**Target:** 16 tasks

### Scope

1. **Test infrastructure** — `tests/integration/known_answer/` with `golden_compare()` utility and `--update-golden` flag
2. **10 per-module known-answer tests** — behavioral assertions (hard pass/fail) + golden snapshot comparison (warn on drift)
3. **1 full pipeline test** — engine → hub → recommendations + anomalies end-to-end
4. **Dashboard greyed-out modules** — Tier-gated modules show as greyed out, not hidden
5. **CLAUDE.md update** — Reflect 10-module architecture

### Testing Approach

- **Behavioral assertions:** Structural properties ("finds >= 2 patterns", "produces >= 1 recommendation"). Resilient to algorithm changes.
- **Golden snapshots:** Full output stored as JSON reference files. Drift produces warnings, not failures. Re-baseline with `--update-golden`.
- **Fixture strategy:** Simulator-based for realistic data (seed=42), hand-crafted JSON for edge cases, mocked services for external dependencies.

### Success Criteria

- [ ] All 10 modules have known-answer tests passing
- [ ] Full pipeline test passes end-to-end
- [ ] Golden snapshots committed for all modules
- [ ] Dashboard shows greyed-out tier-gated modules
- [ ] CLAUDE.md reflects Phase 1 changes
- [ ] No regressions in existing 1,416 tests

---

## Phase 3: Issue Triage & GitHub Roadmap (Queued)

**Prerequisite:** Phase 2 complete (known-answer tests provide baseline for evaluating issue impact)

### Scope

1. **Audit all open GitHub issues** against leaner architecture
2. **Close issues** targeting archived modules with "archived" label
3. **Close issues** that dissolved due to simplification
4. **Re-prioritize** surviving issues with Phase 1 context
5. **File new issues** discovered during audit
6. **Create GitHub milestones** for Phases 4 and 5
7. **Create GitHub project board** for tracking

### Expected Outcome

- Open issue count reduced by ~50%
- Surviving issues prioritized by: security > reliability > performance > architecture
- Milestones created for Phase 4 (Fix) and Phase 5 (UI)

---

## Phase 4: Fix & Optimize (Queued)

**Prerequisite:** Phase 3 complete (prioritized issue list)

### Priority Order

1. **Security** — API auth, CORS, credential handling, input validation
2. **Reliability** — Silent failure logging, unbounded collection guards, graceful degradation
3. **Performance** — Blocking I/O elimination, N+1 query optimization, cache efficiency
4. **Architecture** — Loose coupling, config-driven registration, interface contracts

### Approach

- Each fix gets a known-answer test (from Phase 2 infrastructure)
- Fixes are incremental — one issue per PR
- Known-answer test regressions block merges

---

## Phase 5: UI — Science-Based Decision Tool (Queued)

**Prerequisite:** Phase 4 complete (reliable, secure backend)

### OODA Framework

| Stage | User Sees | ARIA Provides |
|-------|-----------|---------------|
| **Observe** | Raw signals, entity states, activity | Data collection with context |
| **Orient** | Baselines, trends, correlations | Statistical framing: "normal" vs "now" |
| **Understand** | Flagged anomalies, identified patterns | ML output with explainability and confidence |
| **Decide** | Automation recommendations with evidence | Approve/reject with predicted impact |

### KPIs

- **Leading:** pattern shifts, correlation changes, drift signals
- **Lagging:** recommendation acceptance rate, anomaly true positive rate, prediction accuracy

### Approach

- Archive dashboard pages that don't serve recommendations or anomaly detection
- Design follows `docs/design-language.md` principles (Tufte, Cleveland & McGill, Gestalt)
- Progressive disclosure: summary → detail → raw data

---

## Long-Term Vision

HA is the proving ground. Once ARIA reliably produces recommendations and detects anomalies against HA data, the architecture generalizes to **any system that produces time-series state data** with patterns worth detecting and actions worth recommending.

Phase 2's known-answer test harness is the key enabler: it proves the intelligence works independent of the data source.

---

## Success Criteria (Overall)

- [x] Module count reduced to < 10 active modules *(Phase 1: 14 → 10)*
- [ ] Every surviving module has a known-answer integration test *(Phase 2)*
- [ ] Full pipeline known-answer test passes *(Phase 2)*
- [ ] Open issue count reduced by 50%+ *(Phase 3)*
- [ ] UI surfaces recommendations and anomalies as primary views *(Phase 5)*
- [ ] GitHub roadmap with milestones covers remaining work *(Phase 3)*
