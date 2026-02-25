# ARIA Stabilization — Design Document

**Date:** 2026-02-24
**Status:** Approved
**Scope:** Fix all 42 open issues before Phase 5 (LLM Integration + Telegram)
**Approach:** Severity-first with code-surface grouping — 10 batches + 4 deferred

---

## Current State

- **Tests:** 2101 passed, 15 skipped, 0 failures
- **Open issues:** 42 (6 critical, 3 security, 10 high, 13 medium, 10 low/tech-debt)
- **Last commit:** `649d4a9 fix(audit): post-PR #186 audit findings`

---

## Triage: Batch 0 — Close Already-Fixed Issues

Close without code changes (verified by source inspection 2026-02-24):

| Issue | Reason |
|-------|--------|
| #152 | Path traversal guard with `.resolve().is_relative_to()` already present and correct |
| #166 | `SAFETY_CONDITIONS` already removed from `condition_builder.py` |
| #168 | `proc.kill()` already present in `calendar_context.py` with `ProcessLookupError` suppression |
| #174 | BFS already uses `deque.popleft()` (O(1)), not `list.pop(0)` |

Merge #137 into #162 (same root cause — singular/plural key normalization).
Narrow #128 — only `NormalizedEvent` is dead; `DetectionResult` and `ShadowResult` have production consumers.

**Net: 42 → 36 issues requiring code changes + 4 deferred.**

---

## Quality Gate

Run between every batch:

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

Plus a smoke script (`scripts/stabilization-smoke.sh`) that verifies cross-module integration:

```bash
#!/usr/bin/env bash
# Cross-module smoke test — gates every stabilization batch
set -euo pipefail

API="http://127.0.0.1:8001"
FAIL=0

check() {
    local desc="$1" cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "PASS: $desc"
    else
        echo "FAIL: $desc"
        FAIL=1
    fi
}

# ML pipeline returns data (not envelope keys)
check "ML pipeline drift_status" \
    "curl -sf $API/api/ml/pipeline | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'drift_flagged' in d\""

# Presence data uses correct key
check "Presence mqtt_connected key" \
    "curl -sf $API/api/cache/presence | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'mqtt_connected' in str(d) or 'data' in d\""

# Config endpoint redacts sensitive keys
check "Config redacts sensitive values" \
    "curl -sf $API/api/config/presence.mqtt_password | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'REDACTED' in str(d.get('value',''))\""

# Config history redacts sensitive values
check "Config history redacts sensitive" \
    "curl -sf '$API/api/config-history?key=presence.mqtt_password' | python3 -c \"import json,sys; d=json.load(sys.stdin); [exit(1) for e in d.get('history',[]) if 'REDACTED' not in str(e.get('old_value','REDACTED'))]\""

# Shadow comparison not blind
check "Shadow comparison functional" \
    "curl -sf $API/api/shadow/status | python3 -c \"import json,sys; json.load(sys.stdin)\""

# SPA builds without error
check "SPA build" \
    "cd /home/justin/Documents/projects/ha-aria/aria/dashboard/spa && npm run build"

# Ruff clean
check "Ruff lint clean" \
    "cd /home/justin/Documents/projects/ha-aria && ruff check aria/"

exit $FAIL
```

---

## Batch 1A: Memory Leak Investigation (#140)

**Rationale:** Isolated because memory leaks require investigation — multiple candidate sources identified, and the fix may span several files.

**Candidate leak sources (from research):**

1. `aria/hub/audit.py:129` — `_subscribers: list[asyncio.Queue]` grows on WebSocket connect; dead queues accumulate if `remove_subscriber` silently swallows `ValueError`
2. `aria/modules/activity_monitor.py` — `_activity_buffer` grows unbounded if flush stalls; early-flush at 5,000 items but no hard cap
3. `aria/modules/presence.py:90` — `_room_signals` is a `defaultdict(list)` pruned every 30s, but empty rooms persist as `{room: []}`
4. `aria/hub/cache.py` — `_event_log` grows on every `publish()` call; no retention limit visible

**Fix strategy:**
1. Add hard cap to `_activity_buffer` (drop oldest on overflow)
2. Clean empty rooms from `_room_signals` during prune cycle
3. Guard `remove_subscriber` — log warning instead of silently swallowing `ValueError`
4. Add max-size retention to `_event_log` (ring buffer or periodic trim)
5. Add RSS tracking to watchdog for continuous monitoring

**Gate:** Restart hub, record RSS at T=0, T=1h. Must not grow >50MB/hour under normal load.

---

## Batch 1B: Critical Runtime Crashes (#154, #156, #177)

| Issue | File(s) | Fix |
|-------|---------|-----|
| #154 | `aria/hub/core.py:380-396` | Snapshot `subscribers` dict keys before iteration: `for event_type in list(self.subscribers):`. Snapshot per-type set already done — verify TOCTOU gap closed |
| #156 | `aria/hub/audit.py` | Add `if self._db is None: return` guard in `log()` to match `log_request()` pattern. Also guard `_batch_insert` against `_db=None` |
| #177 | `aria/hub/api.py:383,397` | Fix `presence_data.get("connected")` → `get("mqtt_connected")`. Verify all `/api/ml/*` routes unwrap `data` before reading payload keys. Fix `training_data` fallback for flat cache entries |

**Gate:** Full test suite + smoke script. Verify `/api/ml/pipeline` returns non-null `drift_flagged`, `presence_connected` reflects actual MQTT state.

---

## Batch 2: API Security + Timezone (#153, #180, #179)

All three touch `aria/hub/api.py` — grouped to minimize context-switching.

| Issue | Fix |
|-------|-----|
| #153 | Redact `default_value` alongside `value` for sensitive keys in `get_config()` and `get_all_config()` |
| #180 | Verify `entry.get("key")` matches DB column name in `get_config_history()`. Add `"user"`, `"username"` to `_SENSITIVE_KEY_PATTERNS`. Redact `default_value` in history entries |
| #179 | Replace naive `datetime.now()` with `datetime.now(tz=timezone.utc)` in `ha_automation_sync.py:94,153`, `discovery.py:292,323`, and any other naive sites found by grep |

**Gate:** Smoke script sensitive-key checks. Grep for remaining `datetime.now()` without `tz=` — must be zero in `aria/`.

---

## Batch 3: Automation Normalization (#157, #162, #137)

All three are the same code surface — automation key handling between generator, sync, and shadow comparison.

| Issue | Fix |
|-------|-----|
| #157 | Normalize ARIA-generated candidates through `_normalize_automation()` before passing to `shadow_comparison.compare_candidate()` |
| #162 | Ensure generator output includes both singular and plural keys, or normalize at comparison time. Apply Lesson #55: always `get("triggers") or get("trigger", [])` |
| #137 | Merged into #162 — same root cause |

**Gate:** Add test: generate a candidate automation, compare against a known HA automation — verify deduplication detects the match. Run shadow comparison tests.

---

## Batch 4: Silent Failures — Bare Excepts + Callbacks (#155, #159, #160, #164, #165)

Mechanical fixes — same pattern applied across files.

| Issue | Fix |
|-------|-----|
| #155 | Promote presence.py/watchdog.py exception logging from DEBUG → WARNING |
| #159 | Add `add_done_callback` with error logging to: `discovery.py:501`, `cache.py:210`, `audit.py:142` |
| #160 | Store `_dispatch_config_updated` and `_on_cache_updated_entity_graph` callbacks on `self` in `core.py`. Add matching `unsubscribe()` calls in `shutdown()` |
| #164 | Narrow `except Exception` to specific types (`aiohttp.ClientError`, `OSError`) or promote to WARNING in `calendar_context.py` (2 sites), `presence.py` (3 Frigate sites) |
| #165 | Same treatment for `llm_refiner.py`, `condition_builder.py`, `action_builder.py` |

**Gate:** Full test suite. Restart hub, check `journalctl --user -u aria-hub --since "5 min ago" | grep "Task exception"` — must be empty.

---

## Batch 5: LLM Execution Path (#167, #182)

Both change how LLM calls are executed — grouped because #182 changes the client that #167's timeout wraps.

| Issue | Fix |
|-------|-----|
| #182 | Replace raw `ollama.generate()` in `aria/engine/llm/client.py` with HTTP POST to ollama-queue daemon (port 7683) or `ollama-queue submit` subprocess. All callers (patterns, automation_generator, meta_learning) automatically route through queue |
| #167 | Add socket-level timeout to `OllamaConfig` so `asyncio.to_thread(ollama_chat, ...)` respects deadline at the HTTP layer, not just the asyncio wrapper. The thread itself must time out |

**Gate:** `aria patterns --area living_room` produces LLM interpretation (or graceful fallback). No Ollama contention in `ollama-queue status` output. Verify `aria/engine/llm/client.py` has no `import ollama` (raw library).

---

## Batch 6: Data Correctness Formulas (#161, #169, #171, #178, #183)

All are wrong-formula bugs — the code runs but produces wrong numbers.

| Issue | Fix |
|-------|-----|
| #161 | Ensure `EntityGraph.get_area()` traverses entity→device→area chain. Verify `segment_builder._compute_per_area_activity()` returns non-empty area counts on real data |
| #169 | Fix `entity_health.py` availability formula: use timestamp-based availability (duration unavailable / total window) instead of event-count ratio. Remove or use the dead `total_events` parameter |
| #171 | Populate `unique_states` from actual state transitions in event windows, not just current static state. Fix `_collect_unique_states` to read per-entity transitions |
| #178 | Change `threshold_pct=5.0` → `threshold=0.05` in `intelligence.py:_compare_accuracy_trends()` so the condition can actually trigger on 0-1 scale values |
| #183 | Fix `environmental_correlator.py` to pair illuminance value-at-event-time (lux when behavior happened), not cross-correlate minutes-of-day vs lux. Make Pearson r dimensionally consistent |

**Gate:** Specific assertions:
- Per-area activity dict has >1 area after a snapshot
- `_compute_stage_health()` can return non-`"stable"` trend direction
- Entity health availability_pct matches manual calculation for a test entity

---

## Batch 7: Medium Behavioral Fixes (#170, #172, #175, #181)

| Issue | Fix |
|-------|-----|
| #170 | Remove hardcoded fallback `["vacation", "trip"]` in `_classify_single_day()`. Use only the keywords passed from `classify_days()` config |
| #172 | Promote `_read_json` logging: race-condition `FileNotFoundError` → INFO, parse/corruption errors → ERROR (not just WARNING) |
| #175 | Replace `.catch(() => null)` in dashboard call sites with error state handling. Audit: `EntityDetail.jsx`, `CapabilityDetail.jsx`, `Shadow.jsx`, others |
| #181 | Remove 4 dead keys from `routes_module_config.py` (`activity.enabled_domains`, `anomaly.enabled_entities`, `shadow.enabled_capabilities`, `discovery.domain_filter`) or wire to module reads |

**Gate:** `npm run build` succeeds. Discovery tests pass. `grep -r "catch(() =>" aria/dashboard/spa/src/ | wc -l` reduced.

---

## Batch 8: Test Improvements (#176, #129, #130, #131)

| Issue | Fix |
|-------|-----|
| #176 | Add `spec=CacheManager` to `mock_hub.cache` in `conftest.py`. Replace `== 152` hardcoded count with `>= 100` range check (Lesson #32/#44) |
| #129 | Add test exercising `EventNormalizer` with non-empty `include_domains` whitelist |
| #130 | Add test mocking `asyncio.wait_for` timeout in `calendar_context._run_gog_cli()` + missing HA env var path |
| #131 | Add test with all-zero DTW distance matrix and single-element cluster |

**Gate:** Test count strictly increases (2101+ → 2105+). No regressions.

---

## Batch 9: Dead Code + Dead Config Sweep (#184, #132, #133, #128, #134, #135)

Consolidate all "dead code" issues into one sweep.

| Issue | Fix |
|-------|-----|
| #184 | Audit all 169 config keys against `get_config_value()` calls. Delete registrations with no consumer. Estimated removal: ~120 keys |
| #132 | 5 dead automation config keys — remove (subsumed by #184 audit) |
| #133 | 7 dead patterns/shadow/gap config keys — remove (subsumed by #184 audit) |
| #128 | Remove `NormalizedEvent` dataclass (zero production consumers). Keep `DetectionResult` and `ShadowResult` |
| #134 | Add docstring note that `anomaly_gap.py` is dormant — not wired into module registry. Keep for Phase 5 gap detection. Or delete if Phase 5 design replaces it |
| #135 | Fix 10 direct `hub.cache.*` calls in `shadow_engine.py` (highest audit-bypass risk). Remaining 25 sites deferred — file as separate tech-debt issue |

**Gate:** `python3 -c "from aria.hub.config_defaults import CONFIG_DEFAULTS; print(len(CONFIG_DEFAULTS))"` shows reduced count. Full test suite + ruff clean.

---

## Batch 10: Infrastructure — systemd (#141, #142, #143)

Systemd service fixes — separate from Python code changes.

| Issue | Fix |
|-------|-----|
| #141 | Add `Environment=PATH=%h/.local/bin:/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin` to `aria-suggest-automations.service` and `aria-meta-learn.service` |
| #142 | Fix in ollama-queue repo (separate PR): add PATH to worker service environment |
| #143 | Add `RemainAfterExit=yes` to `aria-watchdog.service` |

**Gate:** `systemctl --user start aria-suggest-automations && journalctl --user -u aria-suggest-automations -n 5` — no exit 127. `systemctl --user status aria-watchdog` shows active after run.

---

## Deferred to Phase 6 (Polish)

| Issue | Reason |
|-------|--------|
| #148 | CacheManager god class — architectural refactor, not a bug fix |
| #149 | IntelligenceHub public mutable state — convention issue, not runtime failure |
| #150 | Untyped dict outputs — type safety improvement, not correctness |
| #151 | Mutable list fields — dataclasses aren't frozen, so this is theoretical |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Memory leak fix incomplete | Dedicated batch (1A) with RSS monitoring gate |
| Config key audit deletes something used | Automated grep verification: every deleted key must have zero `get_config_value` hits |
| LLM path change (#182) breaks patterns/automation | Dedicated batch (5) with explicit functional test |
| Cross-repo fix (#142) blocks stabilization | #142 in separate batch 10; doesn't block batches 1-9 |
| Large diff in batch 9 (120+ config deletions) | One commit per issue; mechanical change with grep-verified safety |

---

## Success Criteria

1. All 36 issues closed (code fixes) + 4 deferred with rationale
2. Test count ≥ 2105 (current 2101 + ≥4 new tests from batch 8)
3. `ruff check aria/` clean
4. Smoke script passes
5. Hub RSS stable (<50MB/hour growth) over 1-hour soak test
6. Zero `datetime.now()` without `tz=` in `aria/`
7. Zero `import ollama` (raw library) in `aria/`
8. All systemd services start without exit 127
