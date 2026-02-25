# UniFi Integration Design

**Date:** 2026-02-25
**Status:** Approved — pending implementation plan
**Research:** `~/Documents/research/2026-02-25-unifi-python-libraries.md`, `~/Documents/research/2026-02-25-unifi-rssi-presence-crossvalidation.md`

---

## Goal

Add UniFi Network (WiFi client presence) and UniFi Protect (camera person detection + face recognition) as supplementary presence signals in ARIA. Both run alongside the existing Frigate MQTT pipeline — neither replaces it.

---

## Architecture

Single `UniFiModule` (`aria/modules/unifi.py`) with two signal pipelines sharing one authenticated aiohttp session:

- **Network pipeline** — REST polling of `/proxy/network/api/s/default/stat/sta` every 30s. No aiounifi dependency (requires Python 3.13+; ARIA runs 3.12). Feeds `network_client_present` and `device_active` signals.
- **Protect pipeline** — `uiprotect` library (Python ≥3.11) for real-time WebSocket events. Feeds `protect_person` signal and tunnels thumbnails into the existing ARIA FaceNet face pipeline.
- **Cross-validation layer** — `_cross_validate_signals()` runs inside `_flush_presence_state()` before Bayesian fusion. Boosts corroborated signals, suppresses contradicted ones.

Auth: `X-API-Key: <UNIFI_API_KEY>` header on all requests. `ssl=False` for Dream Machine self-signed cert.

---

## Python Libraries

| Component | Library | Rationale |
|-----------|---------|-----------|
| Network (WiFi clients) | `aiohttp` (raw) | aiounifi requires Python 3.13+; REST API is simple enough to call directly |
| Protect (cameras) | `uiprotect` v10.2.1+ (uilibs/uiprotect) | Handles binary WebSocket protocol; exposes `get_event_thumbnail()`; Python ≥3.11; HA-native |

**uiprotect must be added to pyproject.toml as an optional dependency** under `[project.optional-dependencies]` → `faces` or new `unifi` group.

---

## Signal Types (4 new + 1 gate)

| Signal | Weight | Decay | Source | Notes |
|--------|--------|-------|--------|-------|
| `network_client_present` | 0.75 | 5 min | UniFi Network AP association | Room-level only if ≥1 AP per room; otherwise home/away |
| `device_active` | 0.40 | 2 min | UniFi Network tx+rx rate | Active data transfer = device in use (not just present) |
| `protect_person` | 0.85 | 3 min | UniFi Protect smart detect | Supplements Frigate `camera_person` |
| `protect_face` | 1.00 | none | UniFi Protect thumbnail → FaceNet | Same pipeline as Frigate face events |
| `home_away` | gate | — | All known devices absent | Not a room signal; gates entire Bayesian flush |

**Note on RSSI:** WiFi AP-association RSSI was evaluated and rejected as a separate room signal. Indoor accuracy is 3–8 m (sticky association, multipath fading). `network_client_present` uses AP association for room mapping, which is reliable only when APs are physically per-room. See research doc for details.

---

## Config Keys

```
unifi.enabled              false  # opt-in; disabled by default
unifi.host                 —      # read from UNIFI_HOST env var; no default
unifi.site                 default
unifi.poll_interval_s      30     # Network client poll interval
unifi.ap_rooms             {}     # JSON: {"office-ap": "office", "bedroom-ap": "bedroom"}
unifi.device_people        {}     # JSON: {"aa:bb:cc:dd:ee:ff": "justin"} — overrides UniFi alias
unifi.rssi_room_threshold  -75    # dBm; below this, AP assignment is ambiguous (weight halved)
unifi.device_active_kbps   100    # kbps threshold above which device is "active"
```

`UNIFI_HOST` env var is read at module init. Stored in `~/.env`, injected via systemd service file.

---

## Network Pipeline Detail

```
Poll /proxy/network/api/s/default/stat/sta every 30s
  ↓
For each connected client:
  1. Resolve person: unifi.device_people[mac] → UniFi alias → None
  2. Resolve room: unifi.ap_rooms[ap_mac] → None
  3. If room known: _add_signal(room, "network_client_present", 0.8, detail, ts)
  4. If tx_bytes_r + rx_bytes_r > device_active_kbps * 1000 / 8:
       _add_signal(room, "device_active", 0.85, detail, ts)
  5. Track seen devices → update home_away gate
```

---

## Protect Pipeline Detail

```
uiprotect WebSocket (real-time push)
  ↓
On SmartDetectZone event with objectType "person":
  1. Resolve room: camera.name → unifi.ap_rooms or camera_rooms discovery
  2. _add_signal(room, "protect_person", 0.85, camera_name, ts)
  3. Fetch thumbnail: uiprotect.get_event_thumbnail(event_id)
  4. Save to ARIA_FACES_SNAPSHOTS_DIR (respects 20 GB cap)
  5. Feed into existing FacePipeline.process_embedding() → auto-label or review queue
```

This reuses the entire existing face pipeline without modification.

---

## Cross-Validation Layer

`_cross_validate_signals(room, signals)` runs in `_flush_presence_state()` after signal collection, before Bayesian fusion. It reads the cached UniFi client state (last poll result) and adjusts signal weights:

| Condition | Action | Rationale |
|-----------|--------|-----------|
| `network_client_present` in room AND `camera_person`/`protect_person` in same room | Multiply both values by 1.15 (cap at 0.95) | Two independent systems agree → stronger evidence |
| `camera_person` in room X AND no known device within two rooms of X | Reduce `camera_person` value by 30% | Likely pet/shadow; Frigate false positive |
| `device_tracker` (HA) AND UniFi contradicts (device not seen) | Reduce `device_tracker` weight by 40% | Stale HA state; UniFi is more current |
| All known devices absent from UniFi | Set `home_away = away`; skip Bayesian flush for all rooms | Nobody home |

**Research basis:** Multi-layer cross-validation reduced false alarms from 63.1% to 8.4% in a 280-device, 2-year study (PMC10864388).

---

## Home/Away Gating

When all known devices (those in `unifi.device_people` + any device seen in the last 24h) drop off the UniFi client list:
- `self._unifi_home_away = False`
- `_flush_presence_state()` skips Bayesian calculation and publishes all rooms as `{probability: 0.0, reason: "away"}`
- Prevents ghost occupancy (lights left on, TV running) from maintaining false presence

Recovery: any known device reconnects → `_unifi_home_away = True` → normal flush resumes next cycle.

---

## Dashboard: Devices Tab

New tab under **Presence → Devices** in the ARIA dashboard:
- Lists all UniFi clients seen in last 24h: MAC, alias, last AP, last seen, assigned person
- Inline edit for `device_people` overrides (saves to config via existing `POST /api/config`)
- Shows `home_away` state + how many known devices are connected
- Shows UniFi module status: `connected / polling / error`

---

## Error Handling

| Failure | Behavior |
|---------|---------|
| UniFi host unreachable | Log warning; skip poll cycle; signals decay naturally via existing mechanism |
| SSL cert error | `ssl=False` on all aiohttp requests (Dream Machine self-signed) |
| API key invalid (401) | Log error; disable module; expose `unifi_last_error` in `/api/faces/stats` |
| uiprotect WebSocket disconnect | Reconnect with exponential backoff (same pattern as Frigate MQTT in presence.py) |
| Protect thumbnail fetch fails | Log + skip face pipeline; still add `protect_person` signal |
| `uiprotect` not installed | Module init logs warning and disables itself gracefully |

---

## Testing Plan

- Unit tests mock `aiohttp.ClientSession` — no live UniFi needed
- Mock `uiprotect.ProtectApiClient` for Protect WebSocket events
- Test RSSI threshold logic (above/below `rssi_room_threshold`)
- Test `device_active` kbps threshold calculation
- Test `home_away` gating: all devices absent → away state → flush skipped
- Test cross-validation boosts/suppression math
- Test face pipeline handoff: Protect thumbnail mock → existing `FacePipeline` mock
- Test graceful degradation: `uiprotect` import error → module disables, no crash
- Integration test: full Network poll + Protect event → Bayesian flush → cache write

---

## Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
unifi = ["uiprotect>=10.0"]
```

Install: `pip install -e ".[unifi]"`

`uiprotect` requires Python ≥3.11 (ARIA is on 3.12 — compatible).
`aiounifi` was evaluated and rejected: requires Python ≥3.13 (incompatible with ARIA's 3.12 venv).

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `aria/modules/unifi.py` | Create — UniFiModule class |
| `aria/modules/__init__.py` | Add UniFiModule import + registration |
| `aria/engine/analysis/occupancy.py` | Add 4 new signal types to SENSOR_CONFIG |
| `aria/hub/config_defaults.py` | Add unifi.* config keys with defaults |
| `aria/dashboard/spa/src/pages/Presence.jsx` | Add Devices tab |
| `tests/hub/test_unifi.py` | Create — unit tests |
| `pyproject.toml` | Add uiprotect optional dependency |
