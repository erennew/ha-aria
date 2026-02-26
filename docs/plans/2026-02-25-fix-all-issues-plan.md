# Fix All 100 ARIA Issues — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Fix all 100 open GitHub issues across the ARIA codebase — models, collectors, analysis, hub, modules, shared, backend API, and frontend — with a judge agent verifying consistency and accuracy after every batch, and a full horizontal + vertical audit at the end.

**Architecture:** Priority-first batches (critical → high Python → high frontend → medium → low), sequential sub-agents (one at a time), judge agent with full-plan context after each batch, conventions document defined in Batch 0 before any code is written.

**Tech Stack:** Python 3.12 (`.venv`), FastAPI, Preact/JSX (esbuild), pytest, aiohttp, asyncio, SQLite, pytest-xdist

---

## Execution Model

```
Batch 0: Define conventions (no code)
   ↓
Batch 1 Sub-Agent → Judge Review → Gate
   ↓
Batch 2a Sub-Agent → Judge Review → Gate
   ↓
Batch 2b Sub-Agent → Judge Review → Gate
   ↓
Batch 2c-i Sub-Agent → Judge Review → Gate
   ↓
Batch 2c-ii Sub-Agent → Judge Review → Gate
   ↓
Batch 2d Sub-Agent → Judge Review → Gate
   ↓
Audit Agent (all changed Python files)
   ↓
Batch 3 Sub-Agent → Judge Review → Gate (npm run build)
   ↓
Batch 4a Sub-Agent → Judge Review → Gate
   ↓
Batch 4b Sub-Agent → Judge Review → Gate
   ↓
Batch 5 Sub-Agent → Judge Review → Gate (npm run build)
   ↓
Final Audit Agent: Horizontal sweep + Vertical trace
   ↓
AAR
```

**Sub-agent rule:** Launch ONE sub-agent at a time. Wait for its output. Run the judge. Fix any judge failures before the next sub-agent.

**Judge agent rule:** The judge receives the full plan (this file) + the diff of changes. It checks 4 things. If any fail, the batch is returned for rework before proceeding.

---

## Judge Agent Protocol

After EVERY batch, run the judge agent using this prompt:

```
You are the Judge Agent for the ARIA fix-all-issues plan.

Your role: verify that the batch just completed is correct, consistent, and complete.

Full plan: [attach this entire plan document]
Diff of changes: [attach git diff of the batch]
Issues targeted in this batch: [list from batch section below]

Verify these 4 things:

1. COMPLETENESS — Was every issue in the batch addressed?
   For each issue number, confirm: (a) the source file was modified, (b) the specific bug described was fixed, (c) a new test exists that would have caught the bug.

2. CONVENTION COMPLIANCE — Does each fix follow the conventions in Batch 0?
   Check: silent returns log at WARNING with context. Guards use exact patterns. Shutdown methods follow template. Empty defaults are typed correctly.

3. TEST QUALITY — Does each new test specifically exercise the fixed path?
   The test must fail on the PRE-fix code and pass on the POST-fix code. A test that passes on both is not a fix test. Check that each test:
   - Has an assert on the specific behavior fixed
   - Does NOT require live HA/MQTT/Frigate connections
   - Has a descriptive name matching the issue (e.g., test_autoencoder_missing_model_logs_warning)

4. NO REGRESSIONS — Do all existing tests still pass?
   Run: cd /home/justin/Documents/projects/ha-aria && .venv/bin/python -m pytest tests/ --timeout=120 -q 2>&1 | tail -5
   Report: passed/failed/errors count.

Output format:
BATCH [N] JUDGE RESULT: [PASS|FAIL]
- Completeness: [PASS|FAIL] — [details on any missing issues]
- Convention: [PASS|FAIL] — [details on any violations]
- Test quality: [PASS|FAIL] — [details on any weak tests]
- Regressions: [PASS|FAIL] — [test count before/after]

If FAIL: List exact issues to rework with specific corrections needed.
If PASS: Confirm: "Batch [N] approved. Proceed to Batch [N+1]."
```

---

## Prerequisites

### Step 1: Initialize progress log

```bash
cd ~/Documents/projects/ha-aria
echo "# ARIA Fix-All Progress Log" > progress.txt
echo "Started: $(date -Iseconds)" >> progress.txt
echo "Baseline: 1904 passed, 14 skipped, 13 errors" >> progress.txt
```

### Step 2: Create worktree

```bash
cd ~/Documents/projects/ha-aria
git worktree add ../ha-aria-fix-all-issues -b fix/all-100-issues
cd ../ha-aria-fix-all-issues
```

### Step 3: Verify test baseline in worktree

```bash
.venv/bin/python -m pytest tests/ --timeout=120 -q 2>&1 | tail -5
```
Expected: ~1904 passed, 13 errors (pre-existing import errors in `tests/synthetic/`)

---

## Batch 0: Define Conventions (No Code)

**Purpose:** All sub-agents read this before touching any file. Defines the exact patterns for the 6 recurring bug types. Lesson #74: fix the convention, not 8 files independently.

### Step 1: Create conventions document

Create `docs/conventions-fix-all-issues.md`:

```markdown
# Fix-All Conventions (Batch 0)

Read this before fixing any issue. Every fix must follow the pattern for its type.

## Convention A: Silent Return → Logged Return

**Pattern name:** silent-return
**Applies to issues:** #199, #200, #201, #202, #204, #207, #208, #228, #245, #257, #263

**Wrong:**
```python
def predict(self, data):
    if self._model is None:
        return None
```

**Correct:**
```python
def predict(self, data):
    if self._model is None:
        model_path = self._model_path or "<not configured>"
        logger.warning("predict() called but model not loaded — path: %s", model_path)
        return TYPED_EMPTY_DEFAULT  # matches return type annotation
```

Rules:
- Log at WARNING (not DEBUG, not INFO)
- Include the resource path or identifier in the log message
- Return a TYPED empty default matching the function's return type annotation:
  - float → 0.0
  - list → []
  - dict → {}
  - None (explicitly documented) → None with a WARNING log
- NEVER return None without a log when the function is expected to return data

## Convention B: Missing Array Guard (Python)

**Pattern name:** null-guard-python
**Applies to issues:** #209, #214, #220, #223, #224, #240

**Wrong:**
```python
result = snapshot["key"]["subkey"]
```

**Correct:**
```python
raw = snapshot.get("key", {})
result = raw.get("subkey")
if result is None:
    logger.warning("snapshot missing key.subkey — snapshot_id: %s", snapshot.get("id", "?"))
    return {}
```

Rules:
- Use `.get()` with a typed default, never bare `[]`
- Log at WARNING with enough context to identify which snapshot/call
- Wrap `json.load()` in try/except json.JSONDecodeError — rename corrupt file to `*.corrupt`, return empty default

## Convention C: Missing Array Guard (JavaScript/JSX)

**Pattern name:** null-guard-js
**Applies to issues:** #271, #276, #283, #288, #105

**Wrong:**
```js
data.map(item => ...)
occupants.length > 0
```

**Correct:**
```js
Array.isArray(data) ? data.map(item => ...) : []
Array.isArray(occupants) && occupants.length > 0
```

Rules:
- Use `Array.isArray(x)` before ANY `.map()`, `.filter()`, `.length` access on data from external sources
- For uPlot: check `Array.isArray(series) && series.length > 0 && series[0].length > 0`
- Do NOT use `x?.length > 0` as a substitute — optional chaining does not check array type

## Convention D: Missing shutdown() Method

**Pattern name:** missing-shutdown
**Applies to issues:** #244, #250, #256

**Template (async module):**
```python
async def shutdown(self) -> None:
    """Cancel in-flight tasks and release resources."""
    if self._task is not None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
    if self._session is not None:
        await self._session.close()
        self._session = None
    logger.debug("%s shutdown complete", self.__class__.__name__)
```

Rules:
- Every module with a `self._task` or `self._session` MUST have a `shutdown()` method
- `shutdown()` must be `async def` if the module is async
- Must be registered by calling `hub.register_module(..., shutdown=self.shutdown)` or equivalent
- Log at DEBUG when shutdown completes (not WARNING — this is normal lifecycle)

## Convention E: Wrong Response Shape (Frontend)

**Pattern name:** response-shape-js
**Applies to issues:** #266, #268, #285, #286

**Principle:** HTTP error fallback objects must match the success response shape exactly (Lesson #98).

Define empty-state constants per data type:
```js
// api.js — add these constants
export const EMPTY_CAPABILITIES = { capabilities: {}, entities: {}, devices: {} }
export const EMPTY_INTELLIGENCE = { predictions: [], anomalies: [], correlations: [] }
export const EMPTY_EVENTS = { events: [], total: 0 }
```

Rules:
- `safeFetch()` must surface non-404 errors to the caller — throw or return `{error: true, status: resp.status}`
- Mutation failures (POST/PUT) must trigger visible user feedback, NOT just `console.error`
- 404 fallbacks use the empty-state constant for that endpoint — never a raw `{}`

## Convention F: Integration Seam — Cross-Layer Contract

**Pattern name:** seam-contract
**Applies to issues:** #255, #258, #260, #262, #264, #292, #267

**Principle:** If it crosses a layer boundary (Python→JS, module→hub, engine→hub), it needs a contract test.

Rules:
- datetime objects → JSON boundary: always call `.isoformat()` before publish/cache-write
- Feature column lists → ML boundary: training and inference must call the same builder function
- API auth headers → CORS: test with `ARIA_API_KEY=test-key` set, not default (no auth)
- hub.get_config_value() → module init: method must exist or module must check hub API before calling
```

### Step 2: Commit the conventions

```bash
git add docs/conventions-fix-all-issues.md
git commit -m "docs: add fix-all conventions (Batch 0) — 6 patterns for 100 issues"
echo "Batch 0 complete: conventions defined" >> progress.txt
```

---

## Batch 1: Critical Issues (8 Issues)

**Sub-agent prompt:**
> You are a Python and JavaScript fix agent. Read `docs/conventions-fix-all-issues.md` first. Then fix all 8 issues below. Convention A applies to issues #199-202. Convention F applies to #205, #267, #292. TDD: write the failing test first, then the fix.

**Issues:**
| # | File | Pattern | Fix |
|---|------|---------|-----|
| #199 | `aria/engine/models/reference_model.py` | seam-contract (F) | Change `*.joblib` glob to `*.pkl` — define `MODEL_EXT = ".pkl"` constant, use in both save and glob |
| #200 | `aria/engine/models/autoencoder.py` | silent-return (A) | Log WARNING + path when model file missing at inference |
| #201 | `aria/engine/models/device_failure.py` | silent-return (A) | Log WARNING + path when model file missing; return `[]` |
| #202 | `aria/engine/models/gradient_boosting.py` | silent-return (A) | Log WARNING + path when model file missing; return `None` with log |
| #203 | `aria/engine/collectors/ha_api.py` | logic-bug | Fix unreachable `elif >= 5` branch — calendar events always parse from wrong column offset |
| #205 | `aria/engine/collectors/snapshot.py` | seam-contract (F) | Add `"presence": {}` to `build_empty_snapshot()` return dict |
| #267 | `aria/dashboard/spa/src/api.js` | seam-contract (F) | Inject `X-API-Key` header from env/config in all `safeFetch` calls |
| #292 | `aria/hub/api.py` | seam-contract (F) | Add `"Content-Type"` to `allow_headers` in CORSMiddleware |

**TDD steps per issue (example for #200):**

**Step 1: Write failing test in `tests/engine/test_models.py`**

```python
def test_autoencoder_missing_model_logs_warning(tmp_path, caplog):
    """#200: missing model file must log WARNING, not return None silently."""
    import logging
    from aria.engine.models.autoencoder import Autoencoder
    ae = Autoencoder(model_dir=str(tmp_path))  # no model files present
    with caplog.at_level(logging.WARNING):
        result = ae.predict({"feature1": 0.5})
    assert result is None or result == {}  # typed empty default
    assert any("model" in r.message.lower() for r in caplog.records if r.levelno == logging.WARNING), \
        "Expected WARNING log about missing model"
```

**Step 2: Run to verify it fails**
```bash
.venv/bin/python -m pytest tests/engine/test_models.py::test_autoencoder_missing_model_logs_warning -v
```

**Step 3: Apply the fix** — per Convention A

**Step 4: Verify test passes**
```bash
.venv/bin/python -m pytest tests/engine/test_models.py::test_autoencoder_missing_model_logs_warning -v
```

Apply same TDD pattern for each issue in this batch.

**Step 5: Run full suite**
```bash
.venv/bin/python -m pytest tests/ --timeout=120 -q 2>&1 | tail -5
```
Expected: same or better than baseline (1904 passed).

**Step 6: Commit each fix separately**
```bash
git add [changed files]
git commit -m "fix(models): log warning when model file missing at inference — closes #200"
# repeat per issue
```

**Step 7: Integration smoke test (required for #267 and #292)**
```bash
ARIA_API_KEY=test-key .venv/bin/python -m aria.hub.core &
sleep 3
# Test auth header
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/api/health  # should 200
# Test CORS Content-Type
curl -s -X OPTIONS http://127.0.0.1:8001/api/models/retrain \
  -H "Origin: http://127.0.0.1:8001" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,X-API-Key" \
  -v 2>&1 | grep "access-control-allow-headers"  # must include Content-Type
kill %1
```

**Step 8: Append to progress.txt**
```bash
echo "Batch 1 complete: $(date -Iseconds) — issues #199,#200,#201,#202,#203,#205,#267,#292" >> progress.txt
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 2a.**

---

## Batch 2a: High Python — Models + Collectors (10 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 10 issues below in `aria/engine/models/`, `aria/engine/collectors/`, and `aria/engine/features/`. Convention A (silent return) applies to most. TDD: failing test → fix → passing test → commit per issue.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #204 | `aria/engine/models/autoencoder.py` | A | Surface MLPRegressor convergence warning via `logger.warning()` — add `verbose=0` + catch `ConvergenceWarning` with `warnings.catch_warnings` and re-emit as log |
| #206 | `aria/engine/models/neural_prophet_forecaster.py` | A | Wrap PyTorch training in try/except, log full traceback at ERROR, return empty default |
| #207 | `aria/engine/collectors/extractors.py` | A | Remove `contextlib.suppress` on `SunCollector.daylight_hours` — log WARNING instead |
| #208 | `aria/engine/models/prophet_forecaster.py` | A | Replace `print()` with `logger.warning()` for training errors |
| #209 | `aria/engine/collectors/snapshot.py` | B | Guard HA-unreachable snapshots: check response validity before writing to disk; log WARNING and skip dedup if HA was unreachable |
| #210 | `aria/engine/features/time_features.py` | F | Fix naive datetime: use `datetime.now(tz=timezone.utc)` — align with UTC sun entity strings |
| #211 | `aria/automation/llm_refiner.py` | A | Fix dead `asyncio.wait_for` timeout — inner urllib timeout fires first; apply outer timeout to the actual network call |
| #212 | `aria/engine/features/vector_builder.py` | F | Add `segment_data` argument to `build_training_data()` — 5 event features are always zero without it |
| #213 | `aria/modules/ml_engine.py` | F | Replace hardcoded `qwen2.5-coder:14b` with `self.hub.get_config_value("ml.model")` |
| #217 | `aria/engine/storage/model_io.py` | A | After `pickle.load()`, validate object has expected methods — raise `ValueError` with log if not, do not silently return invalid object |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/engine/ --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 2b.**

---

## Batch 2b: High Python — Analysis + Features (5 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 5 issues below in `aria/engine/analysis/`, `aria/engine/predictions/`, and `aria/automation/`. Convention B (null guard) and Convention A (silent return) apply. TDD required.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #214 | `aria/automation/validator.py` | B | Add `if entity_graph is None: logger.warning(...); return []` before `entity_graph.has_entity()` call |
| #215 | `aria/engine/predictions/scoring.py` | B | Wrap `METRIC_TO_ACTUAL` lambda dict access in try/except KeyError — log WARNING, skip entity, do not drop silently |
| #223 | `aria/engine/analysis/` (anomalies, baselines, correlations) | B | Replace all bare `snap["key"]` with `snap.get("key")` + null guard + WARNING log — audit all 3 files |
| #224 | `aria/engine/analysis/reliability.py` | B | Guard `snap["date"]` — use `snap.get("date")` with WARNING + skip on missing |
| #226 | `aria/engine/analysis/explainability.py` | A | Add `.ndim` check before `shap_values` use — handle both classification (2D) and regression (1D) shapes correctly |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/engine/ --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 2c-i.**

---

## Batch 2c-i: High Python — Hub Core (8 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. You are fixing `aria/hub/core.py` and `aria/hub/routes_faces.py`. This file is touched by MULTIPLE issues — you must fix ALL 8 issues in a single pass. Read the whole file first, understand all interactions, then apply all fixes together. TDD required.

**Issues (all in or near hub core):**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #229 | `aria/hub/core.py` | D | Store the 2 subscriber closures in `initialize()` on `self._subscribers` list; call `hub.unsubscribe()` for each in `shutdown()` |
| #231 | `aria/hub/routes_faces.py` | A | Return 500 (not 200) when `add_embedding()` fails — add error check, log at ERROR |
| #233 | `aria/hub/api.py` | A | When `ARIA_API_KEY` env var is missing, log startup WARNING: "auth disabled — destructive endpoints unprotected" |
| #236 | `aria/shared/event_store.py` | A | Replace `bare except: pass` on migration with `except Exception as e: logger.error("migration failed: %s", e)` then re-raise |
| #237 | `aria/hub/core.py` | A | In `schedule_task()`, add error callback to done-callback chain: `task.add_done_callback(lambda t: logger.error(...) if t.exception() else None)` |
| #238 | `aria/shared/event_store.py` | D | Re-establish persistent aiosqlite connection if it drops — add reconnect logic in `_get_conn()` |
| #240 | `aria/shared/ha_automation_sync.py` | B | Validate HA API response is a list before iterating — `if not isinstance(resp, list): logger.warning(...); return []` |
| #241 | `aria/watchdog.py` | A | Add out-of-band health proof: write a heartbeat file (`~/ha-logs/watchdog/aria-heartbeat`) on each successful check; watchdog detects its own crash if heartbeat goes stale |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/hub/test_hub.py tests/hub/test_api.py tests/hub/test_watchdog.py --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 2c-ii.**

---

## Batch 2c-ii: High Python — Modules (9 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 9 issues in `aria/modules/`. Convention D (shutdown) applies to #244 and #250. Convention F (seam contract) applies to #255 and #258. TDD required.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #244 | `aria/modules/ml_engine.py` | D | Add `async def shutdown()` — cancel in-flight training task, release resources per Convention D template |
| #246 | `aria/modules/orchestrator.py` | B | Add `if self._session is None: logger.warning(...); return` guard before `self._session` use |
| #249 | `aria/modules/presence.py` | A | UniFi `home=False` gate: log at INFO before clearing signal history (`"UniFi home=False — clearing %d signals for %s"`) so operator can see the gate firing |
| #250 | `aria/modules/activity_monitor.py` | D | Add `async def shutdown()` — flush event buffer before cancelling, per Convention D |
| #252 | `aria/modules/presence.py` | D | Replace per-event `aiohttp.ClientSession()` with module-level `self._session` created in `initialize()`, closed in `shutdown()` |
| #255 | `aria/modules/unifi.py` | F | Convert datetime objects to ISO strings before publish: `signal["timestamp"] = signal["timestamp"].isoformat()` |
| #258 | `aria/modules/unifi.py` | F | Replace `hub.get_config_value()` call with correct hub API: `hub.get_config("unifi.host")` (check actual hub API) |
| #260 | `aria/modules/ml_engine.py` | F | Align 12 rolling-window feature names between `MLEngine` and sklearn training — extract shared constant list |
| #261 | `aria/hub/core.py` | D | Wrap `on_event()` dispatch in `asyncio.wait_for(handler(event), timeout=5.0)` — log WARNING on timeout, do not block bus |
| #262 | `aria/engine/collectors/snapshot.py` | F | Write `time_features` dict to intraday snapshot — call `TimeFeatureBuilder().build()` in snapshot collector |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/hub/ --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 2d.**

---

## Batch 2d: High Python — Backend API (3 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix 3 issues in `aria/hub/api.py`. These are all small, targeted fixes. TDD required.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #293 | `aria/hub/api.py` | F | `GET /api/settings/discovery` returning JSON `{"error": "..."}` with 200 status — change to return HTTP 500 when underlying call fails |
| #295 | `aria/hub/api.py` | B | `/api/events` endpoint: add `limit` query param (default 100, max 1000) — slice the event list before returning |
| #296 | `aria/hub/api.py` | D | `/api/presence/thumbnail` proxy to Frigate: wrap in `asyncio.wait_for(..., timeout=5.0)` — return 504 on timeout |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/hub/test_api.py --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Audit Agent.**

---

## Silent Failure Audit Agent (Post Batch 2)

**Purpose:** Catch any remaining silent failures in all Python files changed across Batches 1–2d. One specialized agent, read-only + report only — no code changes.

**Agent prompt:**
> You are the ARIA silent-failure auditor. Scan every Python file changed in this branch (get list from `git diff main --name-only | grep '\.py$'`). For each file, check:
> 1. Any `except` block that logs nothing before returning a fallback
> 2. Any `return None` or `return []` without a preceding `logger.warning()`
> 3. Any bare `json.load()` without try/except
> 4. Any `asyncio.create_task()` without a done-callback for error visibility
> 5. Any datetime object passed to `json.dumps()` or `hub.publish()` without `.isoformat()`
>
> Report: file:line, issue type, severity (HIGH/MEDIUM). Do NOT fix. Output to `tasks/audit-post-batch2.md`.

```bash
# After audit agent completes:
cat tasks/audit-post-batch2.md
# If HIGH severity findings exist: fix them before Batch 3
# If only MEDIUM: create GitHub issues for future cycle
```

**→ JUDGE AGENT: Review audit report. If HIGH findings exist, create fix tasks before Batch 3.**

---

## Batch 3: High Frontend (10 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 10 high-priority JavaScript issues below. Convention C (Array.isArray guard), Convention E (response shape), and Convention F (seam contract) apply. Start with the ROOT CAUSE fixes first (#266 and #267 — already done in Batch 1), then fix derived issues. TDD: write Jest tests or inline test assertions where applicable. Run `npm run build` after each issue to confirm no build errors.

**Root cause first — fix `api.js` comprehensively:**

**Step 1: Define empty-state constants in `aria/dashboard/spa/src/api.js`**

Per Convention E — these are used as fallbacks throughout.

**Issues (fix in order — root causes before derived):**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #266 | `aria/dashboard/spa/src/api.js:88-92` | E | `safeFetch`: return `{error: true, status: resp.status, message: resp.statusText}` for non-404 HTTP errors; callers can check `result.error` |
| #268 | `aria/dashboard/spa/src/store.js:77` | E | Replace `{}` fallback with typed empty-state constant for the endpoint (e.g., `EMPTY_CAPABILITIES`) |
| #270 | `aria/dashboard/spa/src/components/CapabilityDetail.jsx` | E | Pass correct body to `putJson()` — add `JSON.stringify(payload)` as second arg |
| #271 | `aria/dashboard/spa/src/components/TimeChart.jsx:23` | C | Guard `data=[[]]` before passing to uPlot: `Array.isArray(series) && series.length > 0 && series[0].length > 0` |
| #272 | `aria/dashboard/spa/src/lib/pipelineGraph.js:273` | — | Fix `##/observe` double-hash: change to `#/observe` |
| #281 | `aria/dashboard/spa/src/pages/Presence.jsx:212-213` | C | Guard `detection.camera?.replace(...)` with optional chaining — `detection.camera?.replace('_', ' ') ?? 'unknown'` |
| #283 | `aria/dashboard/spa/src/pages/Correlations.jsx:22-27` | C | Add `Array.isArray(matrix)` guard before `buildMatrix()` — return empty UI state if not array |
| #285 | `aria/dashboard/spa/src/components/DataCuration.jsx:207-223` | E | In mutation catch block: call `setError(e.message)` or equivalent to surface failure — not just `console.error` |
| #286 | `aria/dashboard/spa/src/pages/Settings.jsx:35-53` | E | Show user-visible error notification on save/reset failure — add `errorMsg` state, render below form |
| #287 | `aria/dashboard/spa/src/pages/Presence.jsx:182` | F | Replace hardcoded Frigate URL with `${API_BASE}/api/presence/thumbnail?...` — route through ARIA backend proxy |

**Step after each fix:**
```bash
cd aria/dashboard/spa && npm run build 2>&1 | tail -10
```
Expected: no errors.

**Full build + smoke check after all 10:**
```bash
cd aria/dashboard/spa && npm run build
# Start hub and verify dashboard loads
aria serve &
sleep 3
curl -s http://127.0.0.1:8001/ui/ | grep -c "aria"  # should be > 0
kill %1
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 4a.**

---

## Batch 4a: Medium Python — Models, Automation, Analysis (12 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 12 medium-priority issues in models, automation, and analysis. Convention A and B apply throughout. TDD required.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #216 | `aria/automation/validator.py` | A | Fix `_restricted=True` generator — restricted domain check always returns True; fix generator expression |
| #218 | `aria/automation/condition_builder.py` | B | Move `_quote_state` import to `aria/shared/` — remove cross-module private import |
| #219 | `aria/automation/trigger_builder.py` | A | Log when numeric_state silently switches to state trigger on parse error |
| #220 | `aria/engine/storage/data_store.py` | B | Wrap all 10 `json.load()` calls — per Convention B: try/except JSONDecodeError, rename corrupt file, return empty default, log WARNING |
| #221 | `aria/automation/template_engine.py` | A | Fix `day_type != "all"` guard — `"all"` not in `DetectionRange` enum; add explicit `if day_type == "all": return True` early exit |
| #222 | `aria/engine/llm/automation_suggestions.py` | F | Escape LLM-supplied entity IDs before YAML interpolation — use `shlex.quote()` or explicit allow-list validation |
| #225 | `aria/engine/llm/client.py` | D | Add `timeout=floor(timeout, 30)` guard to `ollama_chat()` — prevent `None` blocking urlopen forever |
| #227 | `aria/engine/analysis/correlations.py` | A | Replace hardcoded `"TARS"` string with configurable EV entity name from config |
| #228 | `aria/engine/analysis/power_profiles.py` | A | `learn_profile()` returns None: add `logger.warning("learn_profile returned None for %s", entity_id)` before return |
| #230 | `aria/engine/analysis/sequence_anomalies.py` | A | Add guard: negative log-prob threshold needs direction comment; add assertion `assert threshold <= 0` to surface misconfiguration |
| #232 | `aria/engine/analysis/baselines.py` | C | Guard partial snapshot on cold start: check for minimum required keys before building baseline; log WARNING if skipping |
| #226* | *(already in 2b — skip)* | | |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/engine/ --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 4b.**

---

## Batch 4b: Medium Python — Hub, Modules, Shared, Backend (19 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 19 medium-priority issues across hub, modules, shared, and backend API. Convention A and D apply throughout. TDD required.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #234 | `aria/hub/core.py` | A | Add try/except in `_prune_stale_data()` — log WARNING with traceback on failure, do not crash hub |
| #235 | `aria/hub/api.py` | B | Validate `CurationUpdate.status` and `tier` fields against allowed enum values — return 422 with message on invalid |
| #239 | `aria/hub/api.py` | — | Remove dead `format` param from audit export; replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` |
| #242 | `aria/faces/bootstrap.py` | A | Replace `bare except:Exception` with `except OSError as e: logger.error(...)` — surface disk-full errors |
| #243 | `aria/shared/event_store.py` | D | Guarantee `aiosqlite` connection closes on abnormal exit — use `async with` or register cleanup in hub shutdown |
| #245 | `aria/shared/ha_automation_sync.py` | A | Guard `self._session is None` — log WARNING and return `[]` instead of returning `None` silently |
| #247 | `aria/shared/constants.py` | B | Increment `DEFAULT_FEATURE_CONFIG` version field on any field addition — add comment: "increment version on every field change" |
| #248 | `aria/faces/pipeline.py` | D | Move synchronous SQLite I/O to `asyncio.to_thread()` — prevents blocking event loop |
| #251 | `aria/shared/day_classifier.py` | A | `_parse_date("")` returns `date.today()` silently — return `None` with WARNING log on empty/invalid input |
| #253 | `aria/modules/shadow_engine.py` | F | Replace `datetime.now()` with `datetime.now(tz=timezone.utc)` throughout |
| #254 | `aria/modules/unifi.py` | B | Add `if self._session is None: logger.warning(...); return None` before `self._session.get()` |
| #256 | `aria/modules/patterns.py` | D | Add `async def shutdown()` — cancel `asyncio.to_thread(ollama_chat)` task per Convention D |
| #257 | `aria/modules/ml_engine.py` | A | Log WARNING at startup when model is untrained: `"MLEngine: no trained model found — predictions will be empty until training completes"` |
| #259 | `aria/modules/discovery.py` | C | Fix TOCTOU race: use a lock around double-classification check on cold start |
| #263 | `aria/engine/models/__init__.py` or caller | A | `predict_with_ml()` silent empty dict: add `is_trained: bool` field to return value — distinguish untrained from zero-predictions |
| #264 | `aria/modules/intelligence.py` | B | Fix `ha_automations` cache type: normalize to `list` at write time — never write `{}` when list is expected |
| #265 | `aria/shared/constants.py` | B | Define `SNAPSHOT_FIELDS` constant with all field name strings — replace 6+ scattered literals |
| #294 | `aria/hub/api.py` | F | Add `ARIA_API_KEY` check to `/api/health` route — or document that health is intentionally public; add `auth_enabled` field to response |
| #297 | `aria/hub/api.py` | B | Validate `/api/data/label` input against allowed label enum — return 422 with allowed list on invalid |
| #298 | `aria/hub/api.py` | D | Add rate limiting to `/api/models/retrain` — use a lock or last-called timestamp, reject with 429 if called within 60s |

**Quality gate:**
```bash
.venv/bin/python -m pytest tests/hub/ tests/engine/ --timeout=120 -q 2>&1 | tail -5
```

**→ JUDGE AGENT: Run judge protocol. Must PASS before Batch 5.**

---

## Batch 5: Medium + Low Frontend (15 Issues)

**Sub-agent prompt:**
> Read `docs/conventions-fix-all-issues.md`. Fix all 15 remaining frontend issues. Convention C (Array.isArray guard) applies to several. Run `npm run build` after each fix. TDD where applicable.

**Issues:**
| # | File | Convention | Fix summary |
|---|------|-----------|-------------|
| #269 | `aria/dashboard/spa/src/store.js:194,248` | E | Add `.catch(err => console.error('fetchCategory failed:', err))` to fire-and-forget calls |
| #273 | `aria/dashboard/spa/src/hooks/useCache.js:25-36` | A | Fix double-fetch race: add `useRef` flag to track in-flight fetch, skip second fetch if one is pending |
| #274 | `aria/dashboard/spa/src/components/PipelineStatusBar.jsx` | A | Remove `shadowStage` dead animation code — `shadowStage` always equals `pipelineStage`; simplify to single stage value |
| #275 | `aria/dashboard/spa/src/components/EntityGraph.jsx` | C | Add null check: `if (!node.entity_id) return` before handler fires |
| #276 | `aria/dashboard/spa/src/pages/PresenceTimeline.jsx` | C | Guard `occupants` with `Array.isArray(occupants) ? occupants : []` before render |
| #277 | `aria/dashboard/spa/src/hooks/useSearch.js:44` | A | Stabilize `fields` array: wrap in `useMemo` with empty dep array, or pass stable ref — fixes infinite render loop |
| #278 | `aria/dashboard/spa/src/lib/PipelineSankey.jsx` | A | Add `mouseleave` handler to Sankey tooltip: `tooltip.style.display = 'none'` |
| #279 | `aria/dashboard/spa/src/lib/format.js` | A | `formatDuration(undefined)` returns NaN: add `if (ms == null || isNaN(ms)) return '—'` guard |
| #280 | `aria/dashboard/spa/src/components/CapabilityCard.jsx` | — | Add `key={item.id || index}` to list render — fixes React key warning |
| #282 | `aria/dashboard/spa/src/components/ActivityFeed.jsx` | D | Clear poll interval on unmount: `useEffect(() => { const id = setInterval(...); return () => clearInterval(id); }, [])` |
| #284 | `aria/dashboard/spa/src/components/MetricCard.jsx` | — | Add loading skeleton while data is undefined — `if (!value) return <div class="skeleton" />` |
| #288 | `aria/dashboard/spa/src/pages/Timeline.jsx` | C | Guard `startDate`/`endDate` undefined before passing to chart: return empty state if either is undefined |
| #289 | `aria/dashboard/spa/src/pages/Anomalies.jsx` | A | Fix lexicographic sort: `anomalies.sort((a, b) => parseFloat(b.score) - parseFloat(a.score))` |
| #290 | `aria/dashboard/spa/src/pages/Predictions.jsx` | D | Invalidate predictions cache on successful retrain POST: call `cache.invalidate('predictions')` after 200 response |
| #291 | `aria/dashboard/spa/src/pages/DataCuration.jsx` | D | Reset bulk-select state on route change: add `useEffect(() => setSelected([]), [currentRoute])` |

**Quality gate:**
```bash
cd aria/dashboard/spa && npm run build 2>&1 | tail -5
```
Expected: Build succeeds, 0 errors.

**→ JUDGE AGENT: Run judge protocol. Must PASS before Final Audit.**

---

## Final Audit: Full Horizontal + Vertical (Required Before AAR)

**This is the capstone verification stage. Two agents run sequentially.**

### Audit Agent A: Horizontal Sweep

**Prompt:**
> You are the ARIA horizontal audit agent. Hit every surface of the ARIA API and verify correct behavior after the fix-all changes. Use the HTTP Route Table in `docs/system-routing-map.md` as your checklist.
>
> For each route group, run the curl commands from `docs/api-reference.md` and record: status code, response shape, no new errors.
>
> Focus especially on:
> 1. All POST/PUT routes — verify `Content-Type` header is accepted (CORS #292 fix)
> 2. All routes when `ARIA_API_KEY=test-key` is set — verify X-API-Key header is required (#267)
> 3. `/api/events` — verify pagination (limit param works, #295)
> 4. `/api/models/retrain` — verify rate limiting (second call within 60s returns 429, #298)
> 5. `/api/settings/discovery` — verify error returns 500 not 200 with error body (#293)
> 6. `/api/presence/thumbnail` with Frigate offline — verify 504 returned within 6s (#296)
>
> Output: `tasks/audit-horizontal.md` with PASS/FAIL per route group + any anomalies found.

### Audit Agent B: Vertical Trace

**Prompt:**
> You are the ARIA vertical trace agent. Trace one complete data path from source to UI.
>
> Execute this exact trace:
> 1. `aria snapshot-intraday` — write an intraday snapshot
> 2. Verify the snapshot JSON file exists at `~/ha-logs/intelligence/` and contains `"presence"` key (fix #205) and `"time_features"` key (fix #262)
> 3. Confirm `aria hub` cache at `GET /api/cache/intelligence` reflects the new snapshot
> 4. Confirm WebSocket pushes `cache_updated` event (open ws and wait 5s)
> 5. Load dashboard at `http://127.0.0.1:8001/ui/` and confirm:
>    - Predictions page renders without crash
>    - Correlations page renders without crash (fix #283)
>    - Presence page renders without crash (fix #281, #287)
>    - Timeline page renders without crash (fix #288)
> 6. Run `aria train` (if model data available) — confirm training logs no convergence warnings without operator visibility (fix #204)
>
> Output: `tasks/audit-vertical.md` with step-by-step PASS/FAIL.

### Final Gate

```bash
# Full test suite — must match or improve baseline
.venv/bin/python -m pytest tests/ --timeout=120 -q 2>&1 | tail -5
```

Expected: ≥1904 passed, ≤13 errors (pre-existing synthetic import errors are acceptable).

```bash
# Frontend build clean
cd aria/dashboard/spa && npm run build 2>&1 | tail -3
```

```bash
# All issues closed
cd ~/Documents/projects/ha-aria
gh issue list --state open --limit 100 | wc -l
```
Expected: 0 (or only issues filed during this run for out-of-scope findings).

---

## AAR (After-Action Review)

After all audits pass:

1. Create `docs/plans/2026-02-25-aar-fix-all-issues.md` using template at `docs/plans/TEMPLATE-AAR.md`
2. Compare planned batches vs actual — what diverged?
3. Classify each divergence: A (silent failure), B (integration), C (cold-start), D (spec drift), E (context), F (planning)
4. Count: how many of the 100 "issues" were confirmed bugs? How many were correct code?
5. Log new lessons found during execution

---

## Quality Gates Summary

| After Batch | Gate Command | Pass Criteria |
|-------------|-------------|---------------|
| 1 | `pytest tests/ -q` + smoke test | ≥1904 passed + CORS/auth verified |
| 2a | `pytest tests/engine/ -q` | No regression |
| 2b | `pytest tests/engine/ -q` | No regression |
| 2c-i | `pytest tests/hub/ -q` | No regression |
| 2c-ii | `pytest tests/hub/ -q` | No regression |
| 2d | `pytest tests/hub/test_api.py -q` | No regression |
| Post-2 Audit | Review `tasks/audit-post-batch2.md` | No HIGH findings outstanding |
| 3 | `npm run build` | 0 build errors |
| 4a | `pytest tests/engine/ -q` | No regression |
| 4b | `pytest tests/hub/ tests/engine/ -q` | No regression |
| 5 | `npm run build` | 0 build errors |
| Final | Full suite + H+V audit | ≥1904 passed + all routes + vertical trace |

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Batch 2c-i has multiple fixes to `hub/core.py` | Single agent reads whole file first; judge verifies no merged conflicts |
| Lesson #83: 40% of static-analysis "bugs" may be correct code | Echo-back gate: agent states exact diagnosis before fixing |
| Context degradation at 17+ issues | Batches capped at 10 issues; 2c split into 2c-i / 2c-ii |
| Pre-existing synthetic import errors in test suite | Baseline documented (13 errors); judge treats these as acceptable |
| Frontend fixes require live visual check | Horizontal audit agent covers key pages; vertical trace covers render path |

---

## Issue Count by Batch

| Batch | Count | Total Running |
|-------|-------|--------------|
| 0 (conventions) | 0 code | 0 |
| 1 (critical) | 8 | 8 |
| 2a (models/collectors) | 10 | 18 |
| 2b (analysis/features) | 5 | 23 |
| 2c-i (hub core) | 8 | 31 |
| 2c-ii (modules) | 10 | 41 |
| 2d (backend API) | 3 | 44 |
| 3 (frontend high) | 10 | 54 |
| 4a (medium Python eng) | 11 | 65 |
| 4b (medium Python hub) | 19 | 84 |
| 5 (medium/low frontend) | 15 | 99 |
| #226 counted in 2b | +1 | 100 |

**Total: 100 issues across 11 code batches + 1 audit pass + final H+V.**
