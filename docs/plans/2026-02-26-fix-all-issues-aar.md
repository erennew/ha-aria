# After-Action Review: Fix All 100 Issues
**Date:** 2026-02-26
**Branch:** `fix/all-100-issues`
**Duration:** ~4 hours (2026-02-25T21:47 → 2026-02-26T01:35 CST)

---

## Result

| Metric | Value |
|--------|-------|
| Issues targeted | ~100 open GitHub issues |
| Issues fixed (real) | ~72 (remainder pre-existing or non-existent components) |
| Test count at baseline | 1,904 passed |
| Test count at completion | 2,084 passed |
| Net new tests | **+180** |
| Judge FAIL rounds | 3 (Batch 2c-ii ×2, Batch 3 ×1, Batch 4b ×1) |
| Follow-up issues filed | 3 (#299, #300, #301) |
| Blocking audit findings | 0 |

---

## Batch Summary

| Batch | Issues | Net Tests | Judge |
|-------|--------|-----------|-------|
| 0 | Conventions doc | — | — |
| 1 | #199–203, 205, 267, 292 | baseline | PASS |
| 2a | #204, 206–213, 217 | +9 | PASS |
| 2b | #214, 215, 223, 224, 226 | +19 | PASS |
| 2c-i | #229, 231, 233, 236–238, 240, 241 | +22 | PASS |
| 2c-ii | #244, 246, 249, 250, 252, 255, 258, 260–262 | +29 | PASS (after 2 reworks) |
| 2d | #293, 296 | +4 | PASS |
| Post-Batch-2 audit | 14 HIGH + 1 MEDIUM | +30 | PASS |
| 3 (frontend) | #266, 268, 270, 271, 281, 283, 285–287 | 0 | PASS (after rework) |
| 4a | #216, 218, 219, 221, 222, 225, 227, 228, 230, 232 | +30 | PASS |
| 4b | #234, 235, 242–243, 245, 247–248, 251, 253–254, 256–257, 259, 263–265, 297–298 | +28 | PASS (after rework) |
| 5 (frontend) | #269, 273, 274, 277 (11 pre-existing) | 0 | PASS |
| **Total** | | **+180** | |

---

## What Worked Well

### 1. Batch + judge rhythm
The pattern of sub-agent implements → spec reviewer → code quality reviewer → judge caught every meaningful defect before it merged. Three reworks happened, but each was caught immediately rather than at final audit. Total judge FAIL rounds: 4 (Batch 2c-ii×2, Batch 3×1, Batch 4b×1).

### 2. Post-Batch-2 silent failure audit
Adding an unscheduled audit after Batch 2 to scan all changed Python files for Cluster A patterns (bare excepts, unguarded json.load, fire-and-forget tasks) caught 14 HIGH findings that the per-issue fixes would have missed. This yielded +30 tests and materially reduced production risk. **Recommend making this audit a standard gate in the Code Factory pipeline.**

### 3. Pre-existing detection saved time
~28 of ~100 issues were pre-existing (fixed in earlier work) or referenced non-existent components (renamed/merged during refactoring). Sub-agents reliably identified these without attempting broken fixes. No time wasted on phantom work.

### 4. Convention document (Batch 0)
Writing the conventions doc before any code changes gave sub-agents a consistent reference for:
- Logging format before silent returns (WARNING with class/method name)
- Shutdown patterns (cancel task, close session, unsubscribe, log DEBUG)
- Seam contract (datetime.isoformat() at publish boundaries)

---

## What Went Wrong / Rework Causes

### Rework 1 — Batch 2c-ii, rolling window stats (#260)
**Root cause:** Partial fix scope. The plan said "use rolling window stats in both training and inference paths." The sub-agent fixed the training path (`_build_training_dataset`) but missed the reference model path (`_build_reference_features`), which still called the shallow stat function. The judge caught the inconsistency.

**Lesson:** When fixing "use X in all places," grep ALL callsites at the start — don't trust the plan's implied scope.

### Rework 2 — Batch 3, double-stringify (#270)
**Root cause:** `putJson` wrapper already calls `JSON.stringify(body)` internally. Sub-agent passed `JSON.stringify({})` as the body, causing double-encoding. The fix was a one-liner but required a rework loop.

**Lesson:** Document wrapper contract at the call site — `putJson(url, payload)` takes a raw object, not a pre-stringified string. This is now documented in `docs/gotchas.md`.

### Rework 3 — Batch 4b, spec deviation (#263) + missing tests
**Root cause:** Sub-agent interpreted "add `is_trained: bool` to the return" as adding a log instead of changing the return contract. Also skipped all 15 regression tests (test count didn't change from Batch 4a). Judge caught both.

**Lesson:** When a spec says "add field X to return value," the sub-agent must change the return statement, not just add logging. Judge check on test count delta is critical — if the count didn't increase, tests weren't written.

---

## Lessons Captured (New)

| # | Lesson | Cluster |
|---|--------|---------|
| 114 | hasattr guard on wrong delegation object silences fallback | A |
| 115 | Cross-correlation series alignment requires value sentinel | A |
| 116 | Test re-implements production logic | D |

**Lesson candidates for future capture (from this session):**
- LLM-to-YAML injection: validating entity IDs at the LLM output boundary (#222)
- Cross-module private import: shared constants extracted to `aria/shared/` (#218)
- Docstring coverage ≠ test coverage: listing an issue in a module docstring without a test function is not coverage (#245 gap in Batch 4b)
- `cancelled` flag in React vs Preact signals: the idiom prevents new fetches but can't cancel in-flight; `AbortController` is the correct tool
- `fields.join('\0') + useMemo`: canonical pattern for stabilizing external array refs in Preact hooks

---

## Integration Seam Risks (from final audit)

| Severity | Risk | Follow-up |
|----------|------|-----------|
| MEDIUM | `Predictions.jsx` expects `ml_predictions` cache as `{data: {predictions: [...], ...}}` (array) — shape is not tested. A dict-vs-array mismatch causes silent empty renders. | Issue #299 |
| LOW | `safeFetch()` JSDoc says setter is called on error; it is not. | Issue #300 |
| LOW | `CACHE_INTELLIGENCE["predictions"]` (aggregate blended) and `CACHE_ML_PREDICTIONS` (entity ML) are distinct flows with no documentation at the fork point. | Issue #301 |

---

## Recommendations for Next Session

1. **Merge:** Branch is clean, all tests pass (2084), final audit PASS_WITH_NOTES. Push and create PR.
2. **Capture deferred lessons:** Write the 5 lesson candidates above before the next sprint.
3. **Address #299 first:** The ml_predictions cache schema contract is the highest-risk seam — a schema change in ml_engine would break the Predictions page silently.
4. **Methodology:** Save the execution methodology to `research/2026-02-25-fix-all-issues-execution-methodology.md` (Task #20).
