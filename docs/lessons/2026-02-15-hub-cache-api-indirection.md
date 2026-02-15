# Lesson: Hub Cache API Indirection

**Date:** 2026-02-15
**System:** ARIA (ha-aria)
**Tier:** lesson
**Category:** integration
**Keywords:** cache, CacheManager, IntelligenceHub, API indirection, async, presence, wrapper pattern
**Files:** `aria/modules/presence.py`, `aria/modules/activity_monitor.py`, `aria/hub.py`

---

## Observation (What Happened)

During presence detection implementation, `aria/modules/presence.py` called `self.hub.cache.set_cache()` and `self.hub.cache.get_cache()` directly on the CacheManager instance. At runtime (first flush cycle, ~30s after startup), this crashed with `'CacheManager' object has no attribute 'set_cache'`. Additionally, `_resolve_room()` was written as a sync method calling the cache synchronously, but the correct hub API is a coroutine requiring `await`.

## Analysis (Root Cause — 5 Whys)

**Why #1:** `set_cache` / `get_cache` don't exist on `CacheManager` — they're methods on `IntelligenceHub` that wrap the cache manager with metadata injection and WebSocket notifications.
**Why #2:** The module author inspected `CacheManager`'s interface directly instead of checking how existing modules call cache methods.
**Why #3:** No convention enforcement — the hub's cache indirection pattern isn't documented or enforced by linting/type checks, so it's easy to bypass by reaching through `self.hub.cache`.

## Corrective Actions

| # | Action | Status | Owner | Evidence |
|---|--------|--------|-------|----------|
| 1 | Fix all cache calls in `presence.py` to use `await self.hub.set_cache()` / `await self.hub.get_cache()` | implemented | Claude | Code fix + test updates (AsyncMock) |
| 2 | Make `_resolve_room()` async to support awaitable cache calls | implemented | Claude | Same fix |
| 3 | Add comment in `hub.py` at `set_cache`/`get_cache` noting modules must use hub methods, not CacheManager directly | proposed | Justin | — |

## Ripple Effects

- Any new ARIA module accessing cache will hit this if the author reads CacheManager instead of existing modules
- The sync-vs-async mismatch compounds the problem — even if someone finds the right method name, calling it without `await` produces a coroutine-never-awaited warning and silent data loss
- Existing modules (`activity_monitor.py`, `intelligence.py`) already use the correct pattern and serve as reference

## Sustain Plan

- [ ] 7-day check: Verify presence module cache reads/writes work through hub after next restart
- [ ] 30-day check: Any new modules follow hub cache pattern (grep for `self.hub.cache.set` or `self.hub.cache.get` — should return zero results)
- [ ] Contingency: If direct CacheManager access is needed for performance, add explicit public methods to CacheManager and update all callers consistently

## Key Takeaway

Always check how existing modules call shared infrastructure — wrapper patterns like hub.set_cache() add logic beyond the underlying manager, and bypassing them causes both API errors and silent behavior loss.
