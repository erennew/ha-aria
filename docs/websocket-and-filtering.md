# WebSocket Connections & Entity Filtering

Reference doc for CLAUDE.md.

## WebSocket Connections

The hub maintains **two separate WebSocket connections** to HA:

1. **Discovery** (`aria/modules/discovery.py`) — listens for `entity_registry/list`, `device_registry/list`, `area_registry/list` (low-frequency registry events)
2. **Activity** (`aria/modules/activity_monitor.py`) — listens for `state_changed` (high-volume, ~22K events/day)

Separated by design: state_changed volume would drown registry events. Each has independent backoff (5s→60s max).

## Entity Filtering (Activity Monitor)

**Phase 2 curation layer:** Entity-level include/exclude from `entity_curation` SQLite table. Loaded on startup, reloaded dynamically via `curation_updated` event bus. Falls back to domain filtering when curation table is empty (first boot).

**Domain fallback (used when curation not loaded):**
**Tracked:** light, switch, binary_sensor, lock, media_player, cover, climate, vacuum, person, device_tracker, fan
**Conditional:** sensor (only if device_class == "power")
**Excluded:** update, tts, stt, scene, button, number, select, input_*, counter, script, zone, sun, weather, conversation, event, automation, camera, image, remote

**Noise suppression:** unavailable↔unknown transitions, same-state-to-same-state

## API Reference

Full curl examples for all endpoints: `docs/api-reference.md`

Key endpoints: `/api/cache/{category}`, `/api/shadow/accuracy`, `/api/pipeline`, `/api/ml/*`, `/api/capabilities/*`, `/api/capabilities/registry`, `/api/capabilities/registry/{id}`, `/api/capabilities/registry/graph`, `/api/capabilities/registry/health`, `/api/config`, `/api/curation/summary`
