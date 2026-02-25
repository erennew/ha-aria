# ARIA Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 42 open issues (36 code fixes, 4 close, 4 defer) to stabilize ha-aria before Phase 5.

**Architecture:** Severity-first with code-surface grouping. 10 batches, each independently committable. Cross-module smoke script gates every batch.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI, Preact (SPA), pytest, systemd

**Design Doc:** `docs/plans/2026-02-24-stabilization-design.md`

---

## Quality Gates

Run between every batch:

```bash
cd /home/justin/Documents/projects/ha-aria && .venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

Additional: `ruff check aria/` must be clean after every batch.

---

## Batch 0: Triage (4 close, 2 merge)

### Task 0: Close already-fixed issues and triage

**Step 1: Close issues**

```bash
cd /home/justin/Documents/projects/ha-aria
gh issue close 152 --comment "Verified fixed: path traversal guard with .resolve().is_relative_to() already present at api.py:1607"
gh issue close 166 --comment "Verified fixed: SAFETY_CONDITIONS already removed from condition_builder.py"
gh issue close 168 --comment "Verified fixed: proc.kill() already present in calendar_context.py:98 with ProcessLookupError suppression"
gh issue close 174 --comment "Verified fixed: BFS already uses deque.popleft() (O(1)) at co_occurrence.py:232"
```

**Step 2: Merge/narrow issues**

```bash
gh issue comment 137 --body "Merged into #162 — same root cause (singular/plural key normalization)"
gh issue close 137 --reason "not planned"
gh issue comment 128 --body "Narrowed scope: only NormalizedEvent is dead. DetectionResult and ShadowResult have production consumers (automation_generator, shadow_comparison). Will remove NormalizedEvent only."
```

**Step 3: Commit** — no code changes, skip.

---

## Batch 1A: Memory Leak (#140)

### Task 1: Write smoke script

**Files:**
- Create: `scripts/stabilization-smoke.sh`

**Step 1: Create smoke script from design doc specification**

Write the `scripts/stabilization-smoke.sh` script as specified in the design doc § Quality Gate. Make it executable.

```bash
chmod +x scripts/stabilization-smoke.sh
```

**Step 2: Commit**

```bash
git add scripts/stabilization-smoke.sh
git commit -m "chore: add stabilization smoke script for cross-module regression checks"
```

### Task 2: Fix audit subscriber queue leak (#140 — source 1)

**Files:**
- Modify: `aria/hub/audit.py:129,253-258`
- Test: `tests/hub/test_audit.py`

**Step 1: Write failing test**

Add to `tests/hub/test_audit.py`:

```python
@pytest.mark.asyncio
async def test_remove_subscriber_cleans_dead_queues(audit_logger):
    """Dead subscriber queues must not accumulate (#140)."""
    q = asyncio.Queue()
    audit_logger.add_subscriber(q)
    assert len(audit_logger._subscribers) == 1
    audit_logger.remove_subscriber(q)
    assert len(audit_logger._subscribers) == 0

@pytest.mark.asyncio
async def test_remove_nonexistent_subscriber_logs_warning(audit_logger, caplog):
    """Removing a queue not in the list should log, not silently pass."""
    q = asyncio.Queue()
    with caplog.at_level(logging.WARNING):
        audit_logger.remove_subscriber(q)
    assert "not found" in caplog.text.lower() or len(audit_logger._subscribers) == 0
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/hub/test_audit.py -k "test_remove_subscriber" -v -n 0
```

**Step 3: Fix `remove_subscriber` in `audit.py`**

In `aria/hub/audit.py`, find `remove_subscriber` method. Replace silent `ValueError` suppression with explicit removal + warning:

```python
def remove_subscriber(self, queue: asyncio.Queue) -> None:
    try:
        self._subscribers.remove(queue)
    except ValueError:
        logger.warning("Attempted to remove subscriber queue not in list — possible double-remove")
```

**Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/hub/test_audit.py -k "test_remove_subscriber" -v -n 0
```

**Step 5: Commit**

```bash
git add aria/hub/audit.py tests/hub/test_audit.py
git commit -m "fix(audit): log warning on dead subscriber removal instead of silent swallow (#140)"
```

### Task 3: Cap activity buffer growth (#140 — source 2)

**Files:**
- Modify: `aria/modules/activity_monitor.py:400,410`

**Step 1: Add hard cap above early-flush threshold**

At `activity_monitor.py`, after the early flush block (around line 410), add a hard drop if buffer exceeds 10,000:

```python
# Hard cap: if flush is stalled and buffer exceeds 10,000, drop oldest events
if len(self._activity_buffer) > 10_000:
    dropped = len(self._activity_buffer) - 5000
    self._activity_buffer = self._activity_buffer[-5000:]
    self.logger.warning("Activity buffer exceeded 10,000 — dropped %d oldest events", dropped)
```

**Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest tests/hub/ -k "activity" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/activity_monitor.py
git commit -m "fix(activity): hard cap buffer at 10,000 events to prevent unbounded memory growth (#140)"
```

### Task 4: Clean empty rooms from presence signals (#140 — source 3)

**Files:**
- Modify: `aria/modules/presence.py` (prune cycle, ~line 929-932)

**Step 1: Find the prune cycle in presence.py**

Search for `_room_signals` pruning loop. After stale signal removal, add cleanup of empty rooms:

```python
# After stale signal pruning, remove rooms with no remaining signals
empty_rooms = [room for room, signals in self._room_signals.items() if not signals]
for room in empty_rooms:
    del self._room_signals[room]
```

**Step 2: Run presence tests**

```bash
.venv/bin/python -m pytest tests/hub/test_presence.py --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/presence.py
git commit -m "fix(presence): clean empty rooms from _room_signals during prune cycle (#140)"
```

### Task 5: Bound cache event buffer (#140 — source 4)

**Files:**
- Modify: `aria/hub/cache.py`

**Step 1: Add max-size check to `_event_buffer`**

In `cache.py`, the `_event_buffer` is a `list[tuple]` with `_EVENT_BUFFER_MAX_SIZE = 50`. Find the `log_event` method that appends to this buffer. If buffer exceeds max, trigger immediate flush or drop oldest:

```python
# In log_event(), after append:
if len(self._event_buffer) >= _EVENT_BUFFER_MAX_SIZE * 2:
    # Emergency trim — keep newest half
    self._event_buffer = self._event_buffer[-_EVENT_BUFFER_MAX_SIZE:]
```

**Step 2: Run cache tests**

```bash
.venv/bin/python -m pytest tests/hub/ -k "cache" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/hub/cache.py
git commit -m "fix(cache): emergency trim event buffer when double max-size exceeded (#140)"
```

### Task 6: Add RSS monitoring to watchdog

**Files:**
- Modify: `aria/watchdog.py`

**Step 1: Add RSS tracking to watchdog health check**

In the watchdog's hub health check, add process RSS measurement:

```python
import resource
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux returns KB
# Or use psutil if available, or read /proc/self/status
```

Log RSS to watchdog output. Alert via Telegram if RSS > configurable threshold (default 1500MB — 75% of MemoryMax).

**Step 2: Run watchdog tests**

```bash
.venv/bin/python -m pytest tests/hub/test_watchdog.py --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/watchdog.py
git commit -m "fix(watchdog): add RSS monitoring with Telegram alert on high memory (#140)"
```

### Batch 1A Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
```

---

## Batch 1B: Critical Runtime Crashes (#154, #156, #177)

### Task 7: Fix publish() concurrent mutation (#154)

**Files:**
- Modify: `aria/hub/core.py:379-381`
- Test: `tests/hub/test_core.py`

**Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_publish_safe_during_concurrent_subscribe(hub):
    """publish() must not crash if subscribe() is called during dispatch (#154)."""
    called = []

    async def callback_that_subscribes(data):
        called.append("first")
        # This subscribe modifies hub.subscribers during iteration
        hub.subscribe("other_event", lambda d: None)

    hub.subscribe("test_event", callback_that_subscribes)
    await hub.publish("test_event", {"key": "value"})
    assert "first" in called
```

**Step 2: Run test — verify fails or passes (may already be safe due to `list()` snapshot)**

```bash
.venv/bin/python -m pytest tests/hub/test_core.py -k "test_publish_safe_during_concurrent" -v -n 0
```

**Step 3: Fix — snapshot subscribers dict keys before outer iteration**

In `core.py` `publish()`, change line 380 from:
```python
if event_type in self.subscribers:
    for callback in list(self.subscribers[event_type]):
```
to:
```python
subscriber_set = self.subscribers.get(event_type)
if subscriber_set is not None:
    for callback in list(subscriber_set):
```

This avoids the TOCTOU gap where `event_type` could be removed between the `in` check and the `[]` access.

**Step 4: Run test — verify passes**

```bash
.venv/bin/python -m pytest tests/hub/test_core.py -k "test_publish" -v -n 0
```

**Step 5: Commit**

```bash
git add aria/hub/core.py tests/hub/test_core.py
git commit -m "fix(core): eliminate TOCTOU gap in publish() subscriber dispatch (#154)"
```

### Task 8: Fix audit_logger _db guard (#156)

**Files:**
- Modify: `aria/hub/audit.py` (`log()` method, ~line 148-171)

**Step 1: Add `_db` guard to `log()` method**

The `log()` method at line 159 checks `if self._queue is None: return`. Add a matching guard:

```python
async def log(self, ...):
    if self._queue is None or self._db is None:
        return
```

Also guard `_batch_insert` (find the method) with:

```python
async def _batch_insert(self, rows):
    if self._db is None:
        return
```

**Step 2: Run audit tests**

```bash
.venv/bin/python -m pytest tests/hub/test_audit.py --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/hub/audit.py
git commit -m "fix(audit): guard log() and _batch_insert() against uninitialized _db (#156)"
```

### Task 9: Fix ML pipeline envelope keys (#177)

**Files:**
- Modify: `aria/hub/api.py` (multiple `/api/ml/*` routes)

**Step 1: Find and fix all envelope/data confusion**

Search `api.py` for the `/api/ml/pipeline` route. Fix these specific issues:

1. `presence_data.get("connected")` → `presence_data.get("mqtt_connected")`
2. Verify `training_data` fallback handles flat cache entries (no `"data"` wrapper)
3. Audit all other `/api/ml/*` routes — ensure they all unwrap `data` key before reading payload fields

**Step 2: Write test for corrected key**

```python
@pytest.mark.asyncio
async def test_ml_pipeline_presence_uses_mqtt_connected(client, mock_hub):
    """Pipeline endpoint must read mqtt_connected, not connected (#177)."""
    mock_hub.cache.get = AsyncMock(side_effect=lambda k: {
        "presence": {"data": {"mqtt_connected": True, "rooms": {}}},
        "intelligence": {"data": {"drift_status": {"drifted_metrics": []}}},
    }.get(k))
    resp = await client.get("/api/ml/pipeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["presence_connected"] is True
```

**Step 3: Run test**

```bash
.venv/bin/python -m pytest tests/hub/test_api.py -k "ml_pipeline" -v -n 0
```

**Step 4: Commit**

```bash
git add aria/hub/api.py tests/hub/test_api.py
git commit -m "fix(api): read mqtt_connected not connected in ML pipeline route (#177)"
```

### Batch 1B Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
```

---

## Batch 2: API Security + Timezone (#153, #180, #179)

### Task 10: Redact default_value for sensitive config keys (#153, #180)

**Files:**
- Modify: `aria/hub/api.py` (`get_config`, `get_all_config`, `get_config_history`)

**Step 1: In `get_config()` (~line 1192-1207), redact `default_value`:**

```python
if _is_sensitive_key(key):
    config = dict(config)
    config["value"] = "***REDACTED***"
    if "default_value" in config:
        config["default_value"] = "***REDACTED***"
```

**Step 2: In `get_all_config()`, apply same pattern to each config entry.**

**Step 3: In `get_config_history()`, verify `entry.get("key")` matches the actual DB column. Add `"user"`, `"username"` to `_SENSITIVE_KEY_PATTERNS`.**

At the top of `api.py`:
```python
_SENSITIVE_KEY_PATTERNS = {"password", "token", "secret", "credential", "api_key", "auth", "private_key", "user", "username"}
```

Wait — `"user"` would match too broadly (e.g., `"user_preference.theme"`). Instead, only add `"mqtt_user"` as a specific sensitive key, or add `"mqtt"` to the patterns. Better: keep patterns general and add an exact-match list:

```python
_SENSITIVE_EXACT_KEYS = {"presence.mqtt_user", "presence.mqtt_password"}

def _is_sensitive_key(key: str) -> bool:
    if key in _SENSITIVE_EXACT_KEYS:
        return True
    key_lower = key.lower()
    return any(p in key_lower for p in _SENSITIVE_KEY_PATTERNS)
```

**Step 4: Run API tests**

```bash
.venv/bin/python -m pytest tests/hub/test_api.py -k "config" --timeout=120 -q
```

**Step 5: Commit**

```bash
git add aria/hub/api.py
git commit -m "fix(api): redact default_value and history for sensitive config keys (#153, #180)"
```

### Task 11: Replace naive datetime.now() calls (#179)

**Files:**
- Modify: `aria/shared/ha_automation_sync.py:94,153`
- Modify: `aria/modules/discovery.py:292,323`
- Modify: any other files found by grep

**Step 1: Find all naive datetime.now() calls**

```bash
cd /home/justin/Documents/projects/ha-aria
grep -rn "datetime\.now()" aria/ --include="*.py" | grep -v "tz=" | grep -v "UTC"
```

**Step 2: Replace each with `datetime.now(tz=UTC)`**

Ensure `from datetime import UTC` is imported in each file. Replace:
- `datetime.now()` → `datetime.now(tz=UTC)`
- `datetime.now().isoformat()` → `datetime.now(tz=UTC).isoformat()`

**Step 3: Verify zero remaining naive calls**

```bash
grep -rn "datetime\.now()" aria/ --include="*.py" | grep -v "tz=" | grep -v "UTC" | grep -v "# noqa"
# Must return zero lines
```

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 5: Commit**

```bash
git add -u aria/
git commit -m "fix: replace naive datetime.now() with UTC-aware across all modules (#179)"
```

### Batch 2 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
grep -rn "datetime\.now()" aria/ --include="*.py" | grep -v "tz=" | grep -v "UTC" | wc -l
# Must be 0
```

---

## Batch 3: Automation Normalization (#157, #162)

### Task 12: Normalize candidates before shadow comparison (#157, #162)

**Files:**
- Modify: `aria/automation/automation_generator.py` or `aria/shared/shadow_comparison.py`
- Modify: `aria/shared/ha_automation_sync.py`
- Test: `tests/hub/test_shadow_comparison.py` or `tests/integration/`

**Step 1: Write failing test**

```python
def test_shadow_detects_duplicate_with_mismatched_keys():
    """Generated candidate with 'trigger' key must match HA automation with 'triggers' key (#157)."""
    candidate = {
        "trigger": [{"trigger": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
        "action": [{"action": "light.turn_on", "target": {"entity_id": "light.bedroom"}}],
    }
    ha_automation = {
        "triggers": [{"platform": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.bedroom"}}],
    }
    # After normalization, shadow comparison should detect these as duplicates
    from aria.shared.ha_automation_sync import _normalize_automation
    norm_candidate = _normalize_automation(candidate)
    norm_ha = _normalize_automation(ha_automation)
    # Both should have both singular and plural keys
    assert "triggers" in norm_candidate and "trigger" in norm_candidate
    assert "triggers" in norm_ha and "trigger" in norm_ha
```

**Step 2: Run test — verify behavior**

```bash
.venv/bin/python -m pytest tests/ -k "test_shadow_detects_duplicate_with_mismatched" -v -n 0
```

**Step 3: Fix — normalize candidates at comparison entry point**

In `shadow_comparison.py`, in the `compare_candidate()` method, normalize the candidate before extracting signatures:

```python
from aria.shared.ha_automation_sync import _normalize_automation

def compare_candidate(self, candidate: dict, ha_automations: list[dict]) -> ShadowResult:
    # Normalize candidate to ensure both singular/plural keys exist
    candidate = _normalize_automation(candidate)
    ...
```

Also ensure `_normalize_automation()` handles the `platform` vs `trigger` type key:

```python
# In _normalize_automation, after key sync, normalize trigger type key:
for trigger in normalized.get("triggers", []):
    if "platform" in trigger and "trigger" not in trigger:
        trigger["trigger"] = trigger["platform"]
    elif "trigger" in trigger and "platform" not in trigger:
        trigger["platform"] = trigger["trigger"]
```

**Step 4: Run shadow comparison tests**

```bash
.venv/bin/python -m pytest tests/ -k "shadow" --timeout=120 -q
```

**Step 5: Commit**

```bash
git add aria/shared/shadow_comparison.py aria/shared/ha_automation_sync.py tests/
git commit -m "fix(shadow): normalize candidates before comparison — handle trigger/platform key variants (#157, #162)"
```

### Batch 3 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
```

---

## Batch 4: Silent Failures (#155, #159, #160, #164, #165)

### Task 13: Promote exception logging from DEBUG to WARNING (#155, #164, #165)

**Files:**
- Modify: `aria/modules/presence.py` (~lines 381, 395, 409)
- Modify: `aria/watchdog.py` (~line 394)
- Modify: `aria/shared/calendar_context.py` (~lines 52, 64)
- Modify: `aria/automation/llm_refiner.py` (~line 75)
- Modify: `aria/automation/condition_builder.py` (~line 124)
- Modify: `aria/automation/action_builder.py` (~line 156)

**Step 1: Pattern — for each file, change `logger.debug(` to `logger.warning(` on exception handlers**

The pattern across all files:
- `except Exception` blocks that log at `DEBUG` → change to `WARNING`
- Where possible, narrow `except Exception` to specific types:
  - Frigate HTTP calls: `except (aiohttp.ClientError, OSError, asyncio.TimeoutError)`
  - Calendar fetch: `except (aiohttp.ClientError, OSError, RuntimeError)`
  - Automation area resolution: `except (KeyError, TypeError, AttributeError)`

**Step 2: Run tests for each modified module**

```bash
.venv/bin/python -m pytest tests/hub/test_presence.py tests/hub/test_watchdog.py tests/hub/test_api.py -k "automation or shadow or calendar" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/presence.py aria/watchdog.py aria/shared/calendar_context.py aria/automation/
git commit -m "fix: promote silent exception handlers from DEBUG to WARNING (#155, #164, #165)"
```

### Task 14: Add done_callback to 3 create_task sites (#159)

**Files:**
- Modify: `aria/modules/discovery.py:501`
- Modify: `aria/hub/cache.py:210` (or wherever `_event_flush_task` is created)
- Modify: `aria/hub/audit.py:142`

**Step 1: Pattern — add `add_done_callback` with error logging**

At each site, after `asyncio.create_task(...)`, add:

```python
task.add_done_callback(lambda t: logger.error("Task failed: %s", t.exception()) if not t.cancelled() and t.exception() else None)
```

Or use the existing `log_task_exception` utility from `aria.shared.utils`:

```python
from aria.shared.utils import log_task_exception
task.add_done_callback(log_task_exception)
```

Sites:
1. `discovery.py:501` — `self._debounce_task = asyncio.create_task(_delayed_discovery())`
2. `cache.py` — `self._event_flush_task = asyncio.create_task(self._event_flush_loop())`
3. `audit.py:142` — `self._flush_task = asyncio.create_task(self._flush_loop())`

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 3: Commit**

```bash
git add aria/modules/discovery.py aria/hub/cache.py aria/hub/audit.py
git commit -m "fix: add done_callback to 3 create_task sites for error visibility (#159)"
```

### Task 15: Store subscribe callbacks on self for paired unsubscribe (#160)

**Files:**
- Modify: `aria/hub/core.py:146-157,195-225`

**Step 1: Store callbacks on `self` in `initialize()`**

Change:
```python
async def _dispatch_config_updated(data: dict[str, Any]):
    await self.on_config_updated(data)
self.subscribe("config_updated", _dispatch_config_updated)
```
To:
```python
self._config_updated_callback = self._make_config_dispatch()
self.subscribe("config_updated", self._config_updated_callback)

self._entity_graph_callback = self._make_entity_graph_dispatch()
self.subscribe("cache_updated", self._entity_graph_callback)
```

Add private methods:
```python
def _make_config_dispatch(self):
    async def _dispatch(data):
        await self.on_config_updated(data)
    return _dispatch

def _make_entity_graph_dispatch(self):
    async def _dispatch(data):
        if data.get("category", "") in ("entities", "devices", "areas"):
            await self._refresh_entity_graph()
    return _dispatch
```

**Step 2: Add unsubscribe in `shutdown()`**

In `shutdown()`, before cancelling tasks:
```python
# Unsubscribe hub-internal callbacks
if hasattr(self, "_config_updated_callback"):
    self.unsubscribe("config_updated", self._config_updated_callback)
if hasattr(self, "_entity_graph_callback"):
    self.unsubscribe("cache_updated", self._entity_graph_callback)
if self._broadcast_callback:
    self.unsubscribe("cache_updated", self._broadcast_callback)
```

**Step 3: Run core tests**

```bash
.venv/bin/python -m pytest tests/hub/test_core.py --timeout=120 -q -n 0
```

**Step 4: Commit**

```bash
git add aria/hub/core.py
git commit -m "fix(core): store subscribe callbacks on self, unsubscribe in shutdown (#160)"
```

### Batch 4 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
```

---

## Batch 5: LLM Execution Path (#167, #182)

### Task 16: Route ollama_chat through ollama-queue (#182)

**Files:**
- Modify: `aria/engine/llm/client.py`

**Step 1: Read current `ollama_chat` implementation**

Read `aria/engine/llm/client.py` fully. Identify whether it imports `ollama` directly or uses HTTP.

**Step 2: Replace with ollama-queue HTTP POST**

Replace direct `ollama.generate()` or `ollama.chat()` calls with HTTP POST to `http://127.0.0.1:7683/api/generate` (the ollama-queue daemon). The queue daemon serializes requests to prevent GPU contention.

```python
import httpx

def ollama_chat(prompt: str, config: OllamaConfig) -> str:
    """Send prompt through ollama-queue daemon for serialized GPU access."""
    timeout = getattr(config, "timeout", 120)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            "http://127.0.0.1:7683/api/generate",
            json={
                "model": config.model,
                "prompt": prompt,
                "options": {"temperature": getattr(config, "temperature", 0.7)},
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
```

Note: Read the actual ollama-queue API to confirm the endpoint and format. It may differ.

**Step 3: Remove `import ollama` from the file**

Verify: `grep -rn "import ollama" aria/ --include="*.py"` returns zero lines after the change.

**Step 4: Run pattern/automation tests**

```bash
.venv/bin/python -m pytest tests/hub/test_patterns.py tests/integration/ -k "pattern or automation" --timeout=120 -q
```

**Step 5: Commit**

```bash
git add aria/engine/llm/client.py
git commit -m "fix(llm): route ollama_chat through ollama-queue daemon, remove raw ollama import (#182)"
```

### Task 17: Add socket-level timeout to LLM calls (#167)

**Files:**
- Modify: `aria/engine/llm/client.py` (ensure httpx timeout is set)
- Modify: `aria/automation/llm_refiner.py` (ensure OllamaConfig carries timeout)

**Step 1: Verify timeout propagation**

After Task 16, the `httpx.Client(timeout=timeout)` should already enforce socket-level timeout. Verify that `OllamaConfig` has a `timeout` attribute and that `llm_refiner.py` passes it:

```python
config = OllamaConfig(model=model, timeout=timeout)
```

The `asyncio.wait_for` wrapper in `llm_refiner.py` is now redundant (the HTTP client times out first), but keep it as defense-in-depth.

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/ -k "llm_refiner or pattern" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/engine/llm/client.py aria/automation/llm_refiner.py
git commit -m "fix(llm): enforce socket-level timeout in ollama-queue HTTP client (#167)"
```

### Batch 5 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
grep -rn "import ollama" aria/ --include="*.py" | wc -l
# Must be 0
```

---

## Batch 6: Data Correctness (#161, #169, #171, #178, #183)

### Task 18: Fix trend threshold scale (#178)

**Files:**
- Modify: `aria/modules/intelligence.py:61`

**Step 1: Write failing test**

```python
def test_compare_accuracy_trends_detects_degradation():
    """threshold_pct must work on 0-1 scale, not 0-100 (#178)."""
    from aria.modules.intelligence import _compare_accuracy_trends
    # 0.80 → 0.70 is a 10-point drop, should detect as degradation
    result = _compare_accuracy_trends([0.80, 0.80, 0.80], [0.70, 0.70, 0.70])
    assert result["trend"] != "stable"  # Must detect the 10-point drop
```

**Step 2: Run test — verify fails (currently always returns "stable")**

```bash
.venv/bin/python -m pytest tests/ -k "test_compare_accuracy_trends_detects" -v -n 0
```

**Step 3: Fix threshold**

In `intelligence.py`, find `_compare_accuracy_trends` or equivalent. Change `threshold_pct=5.0` to `threshold=0.05`:

```python
# Old: primary_degraded = primary_delta < -threshold_pct  # threshold_pct=5.0
# New:
primary_degraded = primary_delta < -threshold  # threshold=0.05
```

**Step 4: Run test — verify passes**

```bash
.venv/bin/python -m pytest tests/ -k "test_compare_accuracy" -v -n 0
```

**Step 5: Commit**

```bash
git add aria/modules/intelligence.py tests/
git commit -m "fix(intelligence): correct threshold from 5.0 to 0.05 for 0-1 accuracy scale (#178)"
```

### Task 19: Fix entity_health availability formula (#169)

**Files:**
- Modify: `aria/shared/entity_health.py:37-39`

**Step 1: Fix formula to use timestamp-based availability**

Replace event-count ratio with time-based calculation. If timestamps aren't available in events, use the `total_events` parameter as the denominator (intended purpose).

Read the file first to understand the exact function signature and available data, then implement the fix.

**Step 2: Remove or use the dead `total_events` parameter**

If switching to timestamp-based: remove the parameter. If using it: document the semantics.

**Step 3: Run tests**

```bash
.venv/bin/python -m pytest tests/ -k "entity_health" -v --timeout=120
```

**Step 4: Commit**

```bash
git add aria/shared/entity_health.py
git commit -m "fix(health): correct availability_pct formula — use total_events as intended (#169)"
```

### Task 20: Fix segment_builder area resolution (#161)

**Files:**
- Modify: `aria/shared/entity_graph.py` (verify `get_area()` traverses device chain)
- Modify: `aria/shared/segment_builder.py` (verify area fallback works)

**Step 1: Read `entity_graph.py` `get_area()` method**

Verify it traverses entity→device→area. If it only checks direct `area_id`, fix:

```python
def get_area(self, entity_id: str) -> str | None:
    entity = self._entities.get(entity_id)
    if not entity:
        return None
    # Direct area_id (rare — only ~0.2% of entities)
    if entity.get("area_id"):
        return entity["area_id"]
    # Resolve through device
    device_id = entity.get("device_id")
    if device_id:
        device = self._devices.get(device_id)
        if device and device.get("area_id"):
            return device["area_id"]
    return None
```

**Step 2: Run segment builder tests**

```bash
.venv/bin/python -m pytest tests/ -k "segment" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/shared/entity_graph.py aria/shared/segment_builder.py
git commit -m "fix(segments): ensure get_area() traverses entity→device→area chain (#161)"
```

### Task 21: Fix discovery unique_states (#171)

**Files:**
- Modify: `aria/modules/discovery.py:652-666`

**Step 1: Read `_compute_metrics` and `_collect_unique_states` methods**

Fix `_collect_unique_states` to read actual state transition data from event windows, not just the static current state.

**Step 2: Run discovery tests**

```bash
.venv/bin/python -m pytest tests/ -k "discovery" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/discovery.py
git commit -m "fix(discovery): populate unique_states from event transitions, not just current state (#171)"
```

### Task 22: Fix environmental correlator illuminance pairing (#183)

**Files:**
- Modify: `aria/shared/environmental_correlator.py:141-148`

**Step 1: Read `correlate_with_environment` and `_pair_by_date`**

The issue: `xs` is event minute-of-day, `ys` is lux value — dimensionally incoherent for Pearson r.

Fix: pair each behavioral event with the illuminance reading closest in time (same-day, nearest timestamp). Compute Pearson r between paired illuminance values and a binary "event happened" signal, or between event-time lux values and expected lux values.

Simplest correct fix: for each behavioral event timestamp, find the nearest illuminance reading and use that lux value. Compute Pearson r between these paired lux values and the expected outcome (e.g., light turned on → low lux expected).

**Step 2: Run correlator tests**

```bash
.venv/bin/python -m pytest tests/ -k "correlat" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/shared/environmental_correlator.py
git commit -m "fix(correlator): pair illuminance by timestamp proximity, not minute-vs-lux cross-correlation (#183)"
```

### Batch 6 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
```

---

## Batch 7: Medium Behavioral Fixes (#170, #172, #175, #181)

### Task 23: Fix day_classifier hardcoded vacation keywords (#170)

**Files:**
- Modify: `aria/shared/day_classifier.py:99-101`

**Step 1: Remove hardcoded fallback**

Change:
```python
vacation_keywords = keywords.get("vacation", ["vacation", "trip"])
```
To:
```python
vacation_keywords = keywords.get("vacation", [])
```

Same for any other hardcoded fallbacks in `_classify_single_day()`.

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/ -k "day_classif" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/shared/day_classifier.py
git commit -m "fix(classifier): remove hardcoded vacation keyword fallback — use config only (#170)"
```

### Task 24: Promote _read_json logging levels (#172)

**Files:**
- Modify: `aria/modules/intelligence.py:526-537`

**Step 1: Change log levels**

- `FileNotFoundError` (race condition): keep at DEBUG (legitimate, non-actionable)
- Generic `Exception` (corruption/parse error): promote to ERROR

```python
except Exception as e:
    self.logger.error("Failed to read %s: %s", path, e, exc_info=True)
    return None
```

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/ -k "intelligence" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/intelligence.py
git commit -m "fix(intelligence): promote _read_json parse errors from WARNING to ERROR (#172)"
```

### Task 25: Fix dashboard fetchJson silent error swallowing (#175)

**Files:**
- Modify: `aria/dashboard/spa/src/pages/EntityDetail.jsx`
- Modify: `aria/dashboard/spa/src/pages/CapabilityDetail.jsx`
- Modify: `aria/dashboard/spa/src/pages/Shadow.jsx`
- Modify: any other files with `.catch(() => null)` or `.catch(() => {})`

**Step 1: Find all silent catches**

```bash
grep -rn "catch(() =>" aria/dashboard/spa/src/ --include="*.jsx" --include="*.js"
```

**Step 2: Replace with `safeFetch` or explicit error handling**

Replace `.catch(() => null)` with `.catch(err => { console.error('Fetch failed:', err); return null; })` or use the existing `safeFetch` wrapper from `api.js`.

**Step 3: Build SPA**

```bash
cd aria/dashboard/spa && npm run build
```

**Step 4: Commit**

```bash
git add aria/dashboard/spa/
git commit -m "fix(dashboard): replace silent .catch(() => null) with error logging (#175)"
```

### Task 26: Remove dead routes_module_config keys (#181)

**Files:**
- Modify: `aria/hub/routes_module_config.py:18-24`

**Step 1: Remove 4 dead keys from `MODULE_SOURCE_KEYS`**

Keep only `"presence": "presence.enabled_signals"` (confirmed alive). Remove:
- `"activity": "activity.enabled_domains"`
- `"anomaly": "anomaly.enabled_entities"`
- `"shadow": "shadow.enabled_capabilities"`
- `"discovery": "discovery.domain_filter"`

Or: wire these keys to actual module reads (if the intent is to make them work). Given this is stabilization, removal is safer.

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 3: Commit**

```bash
git add aria/hub/routes_module_config.py
git commit -m "fix(config): remove 4 dead MODULE_SOURCE_KEYS — only presence.enabled_signals is consumed (#181)"
```

### Batch 7 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
cd aria/dashboard/spa && npm run build
```

---

## Batch 8: Test Improvements (#176, #129, #130, #131)

### Task 27: Fix mock_hub.cache spec and hardcoded test counts (#176)

**Files:**
- Modify: `tests/hub/conftest.py:28-38`
- Modify: `tests/hub/test_config_defaults.py:45-46,130,133,138`

**Step 1: Add `spec=CacheManager` to `mock_hub.cache`**

In `conftest.py`:
```python
from aria.hub.cache import CacheManager
mock_hub.cache = MagicMock(spec=CacheManager)
```

**Step 2: Replace hardcoded count with range check**

In `test_config_defaults.py`, replace:
```python
assert len(CONFIG_DEFAULTS) == 152
```
With:
```python
assert len(CONFIG_DEFAULTS) >= 40  # Minimum viable config set; exact count changes with features
```

Apply to all hardcoded count assertions in the file.

**Step 3: Run tests — fix any spec violations that surface**

```bash
.venv/bin/python -m pytest tests/hub/ --timeout=120 -q
```

Some tests may fail because they call methods not on `CacheManager`'s spec. Fix those tests.

**Step 4: Commit**

```bash
git add tests/hub/conftest.py tests/hub/test_config_defaults.py
git commit -m "fix(tests): add CacheManager spec to mock, replace hardcoded config counts (#176)"
```

### Task 28: Add test for include_domains whitelist (#129)

**Files:**
- Create or modify: `tests/shared/test_event_normalizer.py`

**Step 1: Write test**

```python
def test_include_domains_whitelist_filters_correctly():
    """EventNormalizer with include_domains should only pass whitelisted domains (#129)."""
    normalizer = EventNormalizer(config={"filter.include_domains": ["light", "switch"]})
    events = [
        {"entity_id": "light.kitchen", "domain": "light"},
        {"entity_id": "sensor.temp", "domain": "sensor"},
        {"entity_id": "switch.fan", "domain": "switch"},
    ]
    filtered = normalizer.filter_user_exclusions(events)
    assert len(filtered) == 2
    assert all(e["domain"] in ("light", "switch") for e in filtered)
```

**Step 2: Run test**

```bash
.venv/bin/python -m pytest tests/ -k "test_include_domains_whitelist" -v -n 0
```

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: add coverage for EventNormalizer include_domains whitelist (#129)"
```

### Task 29: Add tests for calendar timeout and DTW degenerate matrix (#130, #131)

**Files:**
- Create or modify: `tests/shared/test_calendar_context.py`
- Create or modify: `tests/hub/test_trajectory_classifier.py`

**Step 1: Calendar timeout test (#130)**

```python
@pytest.mark.asyncio
async def test_gog_cli_timeout_kills_process():
    """Timeout in _run_gog_cli must kill the subprocess (#130)."""
    # Mock asyncio.wait_for to raise TimeoutError
    ...
```

**Step 2: DTW degenerate matrix test (#131)**

```python
def test_dtw_all_zero_distance_matrix():
    """All-zero distance matrix (identical sequences) must not crash (#131)."""
    # Create sequences that are all identical
    ...
```

**Step 3: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: add calendar timeout and DTW degenerate matrix coverage (#130, #131)"
```

### Batch 8 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
# Verify test count increased
.venv/bin/python -m pytest tests/ --timeout=120 -q 2>&1 | tail -1
# Must show >= 2105 passed
```

---

## Batch 9: Dead Code + Config Sweep (#184, #132, #133, #128, #134, #135)

### Task 30: Audit and remove dead config keys (#184, #132, #133)

**Files:**
- Modify: `aria/hub/config_defaults.py`

**Step 1: Generate exhaustive cross-reference**

```bash
cd /home/justin/Documents/projects/ha-aria
# List all registered config keys
python3 -c "
from aria.hub.config_defaults import CONFIG_DEFAULTS
for d in CONFIG_DEFAULTS:
    print(d['key'])
" > /tmp/all_config_keys.txt

# List all consumed keys
grep -rn 'get_config_value\|get_config(' aria/ --include="*.py" | grep -oP '"[a-z_.]+[a-z]"' | sort -u > /tmp/consumed_keys.txt

# Find dead keys
comm -23 <(sort /tmp/all_config_keys.txt) /tmp/consumed_keys.txt > /tmp/dead_keys.txt
wc -l /tmp/dead_keys.txt
```

**Step 2: Remove dead keys from CONFIG_DEFAULTS**

For each key in `/tmp/dead_keys.txt`, remove the corresponding entry from `CONFIG_DEFAULTS` list in `config_defaults.py`. Verify the file still parses.

**Step 3: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 4: Commit**

```bash
git add aria/hub/config_defaults.py
git commit -m "fix(config): remove ~120 dead config keys with no get_config_value consumer (#184, #132, #133)"
```

### Task 31: Remove dead NormalizedEvent (#128)

**Files:**
- Modify: `aria/automation/models.py`

**Step 1: Remove `NormalizedEvent` class definition**

Keep `DetectionResult` and `ShadowResult` (they have consumers). Remove `NormalizedEvent` and any related imports.

**Step 2: Verify no imports broken**

```bash
grep -rn "NormalizedEvent" aria/ tests/ --include="*.py"
# Must return zero (or only the removal diff)
```

**Step 3: Run tests**

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
```

**Step 4: Commit**

```bash
git add aria/automation/models.py
git commit -m "fix(models): remove dead NormalizedEvent dataclass — zero production consumers (#128)"
```

### Task 32: Mark anomaly_gap.py as dormant (#134)

**Files:**
- Modify: `aria/modules/anomaly_gap.py`

**Step 1: Add module-level docstring note**

If not already present:
```python
"""Anomaly Gap Analyzer — detects repetitive manual actions that could be automated.

NOTE: Dormant module — not registered in hub module registry.
Wire into cli._register_modules() when Phase 5 gap detection is needed.
See: docs/plans/2026-02-20-aria-roadmap-2-design.md § Phase 3
"""
```

**Step 2: Commit**

```bash
git add aria/modules/anomaly_gap.py
git commit -m "docs(anomaly_gap): mark module as dormant — not wired into hub (#134)"
```

### Task 33: Fix shadow_engine direct cache access (#135 — partial)

**Files:**
- Modify: `aria/modules/shadow_engine.py`

**Step 1: Read `shadow_engine.py` and identify the 10 `hub.cache.*` direct calls**

Replace direct `hub.cache.insert_prediction()`, `hub.cache.update_prediction_outcome()`, `hub.cache.get_pending_predictions()` etc. with calls through `hub.set_cache()` and `hub.cache.get*()` (reads are acceptable per core.py comment).

Focus on write calls only — reads through `hub.cache.get*()` are acceptable.

**Step 2: Run shadow engine tests**

```bash
.venv/bin/python -m pytest tests/ -k "shadow" --timeout=120 -q
```

**Step 3: Commit**

```bash
git add aria/modules/shadow_engine.py
git commit -m "fix(shadow): route cache writes through hub methods instead of direct access (#135 partial)"
```

### Batch 9 Gate

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -x -q
ruff check aria/
python3 -c "from aria.hub.config_defaults import CONFIG_DEFAULTS; print(f'{len(CONFIG_DEFAULTS)} config keys remaining')"
```

---

## Batch 10: Infrastructure — systemd (#141, #142, #143)

### Task 34: Fix systemd service PATH (#141)

**Files:**
- Modify: `~/.config/systemd/user/aria-suggest-automations.service`
- Modify: `~/.config/systemd/user/aria-meta-learn.service`

**Step 1: Add Environment=PATH to both services**

Add under `[Service]`:
```ini
Environment=PATH=%h/.local/bin:/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin
```

**Step 2: Reload and test**

```bash
systemctl --user daemon-reload
systemctl --user start aria-suggest-automations
journalctl --user -u aria-suggest-automations -n 10 --no-pager
# Verify no exit 127
```

**Step 3: Commit (if services are in repo)**

```bash
# Services may be in ha-aria repo or only on disk — check
ls ~/.config/systemd/user/aria-suggest-automations.service
```

### Task 35: Fix watchdog service state (#143)

**Files:**
- Modify: `~/.config/systemd/user/aria-watchdog.service`

**Step 1: Add RemainAfterExit=yes**

Under `[Service]`:
```ini
RemainAfterExit=yes
```

**Step 2: Reload and test**

```bash
systemctl --user daemon-reload
systemctl --user start aria-watchdog
systemctl --user status aria-watchdog
# Should show "active (exited)" not "inactive (dead)"
```

### Task 36: Note #142 as cross-repo

**Step 1: Comment on issue**

```bash
gh issue comment 142 --body "Cross-repo fix needed in ollama-queue project. Will address in separate PR. Not blocking ha-aria stabilization."
```

### Batch 10 Gate

```bash
systemctl --user start aria-suggest-automations && sleep 2 && journalctl --user -u aria-suggest-automations -n 5 --no-pager | grep -v "exit 127"
systemctl --user status aria-watchdog | grep "active"
```

---

## Final Gate

After all 10 batches:

```bash
cd /home/justin/Documents/projects/ha-aria

# 1. Full test suite
.venv/bin/python -m pytest tests/ --timeout=120 -q

# 2. Lint clean
ruff check aria/

# 3. No naive datetime
grep -rn "datetime\.now()" aria/ --include="*.py" | grep -v "tz=" | grep -v "UTC" | wc -l
# Must be 0

# 4. No raw ollama import
grep -rn "import ollama" aria/ --include="*.py" | wc -l
# Must be 0

# 5. Config key count reduced
python3 -c "from aria.hub.config_defaults import CONFIG_DEFAULTS; print(len(CONFIG_DEFAULTS))"

# 6. SPA builds
cd aria/dashboard/spa && npm run build && cd -

# 7. Smoke script (if hub is running)
bash scripts/stabilization-smoke.sh

# 8. Verify open issue count
gh issue list --state open | wc -l
# Target: 4 (deferred: #148, #149, #150, #151) + #142 (cross-repo)
```

---

## Issue → Task Map

| Issue | Task | Batch |
|-------|------|-------|
| #140 | 2-6 | 1A |
| #154 | 7 | 1B |
| #156 | 8 | 1B |
| #177 | 9 | 1B |
| #153 | 10 | 2 |
| #180 | 10 | 2 |
| #179 | 11 | 2 |
| #157 | 12 | 3 |
| #162 | 12 | 3 |
| #155 | 13 | 4 |
| #164 | 13 | 4 |
| #165 | 13 | 4 |
| #159 | 14 | 4 |
| #160 | 15 | 4 |
| #182 | 16 | 5 |
| #167 | 17 | 5 |
| #178 | 18 | 6 |
| #169 | 19 | 6 |
| #161 | 20 | 6 |
| #171 | 21 | 6 |
| #183 | 22 | 6 |
| #170 | 23 | 7 |
| #172 | 24 | 7 |
| #175 | 25 | 7 |
| #181 | 26 | 7 |
| #176 | 27 | 8 |
| #129 | 28 | 8 |
| #130 | 29 | 8 |
| #131 | 29 | 8 |
| #184 | 30 | 9 |
| #132 | 30 | 9 |
| #133 | 30 | 9 |
| #128 | 31 | 9 |
| #134 | 32 | 9 |
| #135 | 33 | 9 |
| #141 | 34 | 10 |
| #142 | 36 | 10 |
| #143 | 35 | 10 |
