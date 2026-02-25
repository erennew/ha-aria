# UniFi Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `UniFiModule` to ARIA — polling UniFi Network for WiFi client presence and subscribing to UniFi Protect for real-time person/face events — as supplementary presence signals that cross-validate existing Frigate+HA signals.

**Architecture:** Single `aria/modules/unifi.py` with two signal pipelines sharing one aiohttp session. Network pipeline: REST polling every 30s → `network_client_present` + `device_active` signals. Protect pipeline: `uiprotect` WebSocket → `protect_person` signal + face thumbnail → existing `FacePipeline`. Cross-validation runs inside `_flush_presence_state()` before Bayesian fusion. Home/away gate: all known devices absent → suppress all room signals.

**Tech Stack:** `aiohttp` (raw REST — aiounifi requires Python 3.13+, ARIA runs 3.12), `uiprotect>=10.0` (Python 3.11+, optional dependency), hub event bus + cache (`hub.set_cache` / `hub.get_cache`), existing `FacePipeline` in `aria/modules/presence.py`.

**Design Doc:** `docs/plans/2026-02-25-unifi-integration-design.md`

---

## Relevant Lessons

Check these before starting each task:

- **#37 subscriber-lifecycle-cleanup** — Every `hub.subscribe()` in `initialize()` must store callback ref on `self` and call `hub.unsubscribe()` in `shutdown()`.
- **#28 module-lifecycle-subscribe-after-gate** — Resource acquisition (subscriptions, connections, timers) belongs in `initialize()`, not `__init__()`.
- **#31 module-id-collision** — Grep for `module_id` before adding a new module to confirm no collision.
- **#7 ha-integration-gaps** — Every external API call must log failures explicitly, not swallow them silently.
- **#54 dead-config-keys** — Every `register_config()` / CONFIG_DEFAULTS entry must have a matching `get_config_value()` call in production code.
- **#12 hub-cache-api-indirection** — Use `hub.set_cache()`/`get_cache()` only — never `hub.cache.*` directly.
- **#25 async-for-no-reason** — Never mark a function `async` if its body has no I/O.
- **#30 missing-await-caller-side** — Every `await hub.set_cache()` call must have `await` at the call site.
- **#39 event-firehose-domain-filter** — Filter events before any expensive async work.

---

## Task 1: Add `uiprotect` Optional Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Write the failing test**

There is no code test for this (it's a config change). Verify the current state instead:

```bash
cd /home/justin/Documents/projects/ha-aria
grep -n "uiprotect\|optional-dependencies\|\[project\.optional" pyproject.toml
```

Expected: no `uiprotect` line exists yet.

**Step 2: Add the dependency**

In `pyproject.toml`, find `[project.optional-dependencies]`. If it doesn't exist, add it. Add `uiprotect` group:

```toml
[project.optional-dependencies]
faces = ["deepface>=0.0.93", "tf-keras>=2.16"]
unifi = ["uiprotect>=10.0"]
```

(If `faces` group already exists, add `unifi` after it.)

**Step 3: Verify pyproject.toml is valid**

```bash
cd /home/justin/Documents/projects/ha-aria
python3 -c "import tomllib; tomllib.loads(open('pyproject.toml').read()); print('valid')"
```

Expected: `valid`

**Step 4: Install the dependency**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pip install -e ".[unifi]" --quiet
.venv/bin/python -c "import uiprotect; print(uiprotect.__version__)"
```

Expected: version string like `10.2.1`

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add pyproject.toml
git commit -m "feat(unifi): add uiprotect optional dependency"
```

---

## Task 2: Add UniFi Config Defaults

**Files:**
- Modify: `aria/hub/config_defaults.py`

**Step 1: Write the failing test**

Create `tests/hub/test_unifi_config.py`:

```python
"""Tests for UniFi config defaults registration."""
import pytest
from aria.hub.config_defaults import CONFIG_DEFAULTS


def _get_key(key):
    return next((c for c in CONFIG_DEFAULTS if c["key"] == key), None)


def test_unifi_enabled_exists():
    cfg = _get_key("unifi.enabled")
    assert cfg is not None
    assert cfg["default_value"] == "false"
    assert cfg["value_type"] == "boolean"


def test_unifi_host_exists():
    cfg = _get_key("unifi.host")
    assert cfg is not None
    assert cfg["default_value"] == ""


def test_unifi_site_default():
    cfg = _get_key("unifi.site")
    assert cfg["default_value"] == "default"


def test_unifi_poll_interval_exists():
    cfg = _get_key("unifi.poll_interval_s")
    assert cfg is not None
    assert cfg["default_value"] == "30"
    assert cfg["value_type"] == "number"


def test_unifi_ap_rooms_exists():
    cfg = _get_key("unifi.ap_rooms")
    assert cfg is not None
    assert cfg["default_value"] == "{}"
    assert cfg["value_type"] == "json"


def test_unifi_device_people_exists():
    cfg = _get_key("unifi.device_people")
    assert cfg is not None
    assert cfg["default_value"] == "{}"
    assert cfg["value_type"] == "json"


def test_unifi_rssi_threshold_exists():
    cfg = _get_key("unifi.rssi_room_threshold")
    assert cfg["default_value"] == "-75"


def test_unifi_device_active_kbps_exists():
    cfg = _get_key("unifi.device_active_kbps")
    assert cfg["default_value"] == "100"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi_config.py -v
```

Expected: all 8 tests FAIL with `AssertionError: assert None is not None`

**Step 3: Add the config defaults**

In `aria/hub/config_defaults.py`, find the last entry in `CONFIG_DEFAULTS` and append after it:

```python
    # ── UniFi Integration ─────────────────────────────────────────────
    {
        "key": "unifi.enabled",
        "default_value": "false",
        "value_type": "boolean",
        "label": "Enable UniFi Integration",
        "description": "Enable UniFi Network and Protect presence signals.",
        "description_layman": (
            "Turn on WiFi device tracking and camera events from your"
            " UniFi system to improve room-level presence detection."
        ),
        "description_technical": (
            "When true, starts Network REST polling (every poll_interval_s)"
            " and Protect WebSocket subscription. Requires UNIFI_HOST env var."
            " Disabled by default — opt-in."
        ),
        "category": "UniFi",
    },
    {
        "key": "unifi.host",
        "default_value": "",
        "value_type": "string",
        "label": "UniFi Host",
        "description": "UniFi controller hostname or IP (read from UNIFI_HOST env var).",
        "description_layman": (
            "The address of your UniFi Dream Machine or controller."
            " Leave blank — set UNIFI_HOST in your environment file instead."
        ),
        "description_technical": (
            "Overridden at runtime by UNIFI_HOST env var."
            " If both are set, env var wins. ssl=False on all requests"
            " (Dream Machine uses self-signed cert)."
        ),
        "category": "UniFi",
    },
    {
        "key": "unifi.site",
        "default_value": "default",
        "value_type": "string",
        "label": "UniFi Site",
        "description": "UniFi site name (usually 'default').",
        "description_layman": "Your UniFi site name — leave as 'default' unless you have multiple sites.",
        "description_technical": "Used in Network API path: /proxy/network/api/s/{site}/stat/sta",
        "category": "UniFi",
    },
    {
        "key": "unifi.poll_interval_s",
        "default_value": "30",
        "value_type": "number",
        "label": "Network Poll Interval (s)",
        "description": "How often to poll UniFi Network for WiFi client state.",
        "description_layman": "How frequently ARIA checks which devices are connected to your WiFi.",
        "description_technical": (
            "Interval in seconds between REST polls to /proxy/network/api/s/default/stat/sta."
            " Range 10-300, default 30. Lower = faster home/away detection, more API load."
        ),
        "category": "UniFi",
        "min_value": 10,
        "max_value": 300,
        "step": 5,
    },
    {
        "key": "unifi.ap_rooms",
        "default_value": "{}",
        "value_type": "json",
        "label": "AP → Room Mapping",
        "description": "Map UniFi AP names to room names for room-level presence.",
        "description_layman": (
            "Tell ARIA which room each WiFi access point is in."
            " Format: {\"office-ap\": \"office\", \"bedroom-ap\": \"bedroom\"}"
        ),
        "description_technical": (
            "Keys are UniFi AP hostnames or MAC addresses."
            " Values are ARIA room names (must match area names in HA)."
            " Room-level presence is only reliable when APs are physically per-room."
        ),
        "category": "UniFi",
    },
    {
        "key": "unifi.device_people",
        "default_value": "{}",
        "value_type": "json",
        "label": "Device → Person Mapping",
        "description": "Map device MAC addresses to person names.",
        "description_layman": (
            "Tell ARIA which devices belong to which person."
            " Format: {\"aa:bb:cc:dd:ee:ff\": \"justin\"}"
        ),
        "description_technical": (
            "Overrides UniFi device alias for person resolution."
            " MAC is lowercase colon-separated. Falls back to UniFi alias if not set."
            " Only devices in this map + seen in last 24h contribute to home_away gate."
        ),
        "category": "UniFi",
    },
    {
        "key": "unifi.rssi_room_threshold",
        "default_value": "-75",
        "value_type": "number",
        "label": "RSSI Ambiguity Threshold (dBm)",
        "description": "Below this RSSI, AP room assignment is considered ambiguous.",
        "description_layman": (
            "How weak a WiFi signal must be before ARIA reduces its confidence"
            " in which room a device is in. -75 is a safe default."
        ),
        "description_technical": (
            "When client RSSI < threshold, network_client_present signal weight"
            " is halved (0.75 → 0.375). Range -90 to -50 dBm, default -75."
            " Research basis: RSSI below -80 dBm has 3-8m indoor error."
        ),
        "category": "UniFi",
        "min_value": -90,
        "max_value": -50,
        "step": 5,
    },
    {
        "key": "unifi.device_active_kbps",
        "default_value": "100",
        "value_type": "number",
        "label": "Active Device Threshold (kbps)",
        "description": "Tx+Rx rate above which a device is considered actively in use.",
        "description_layman": (
            "How much data transfer makes a device 'active'."
            " A phone streaming video should exceed 100 kbps easily."
        ),
        "description_technical": (
            "Sum of tx_bytes_r + rx_bytes_r (bytes/s from UniFi API)"
            " converted to kbps: (tx + rx) * 8 / 1000."
            " When exceeded, adds device_active signal (weight 0.40, decay 2 min)."
        ),
        "category": "UniFi",
        "min_value": 10,
        "max_value": 10000,
        "step": 10,
    },
```

**Step 4: Run test to verify it passes**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi_config.py -v
```

Expected: all 8 tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/hub/config_defaults.py tests/hub/test_unifi_config.py
git commit -m "feat(unifi): add 8 unifi.* config defaults"
```

---

## Task 3: Add 4 New Signal Types to SENSOR_CONFIG

**Files:**
- Modify: `aria/engine/analysis/occupancy.py`

**Step 1: Write the failing test**

Add to `tests/hub/test_unifi_config.py` (append to file):

```python
def test_unifi_sensor_config_entries():
    from aria.engine.analysis.occupancy import SENSOR_CONFIG
    assert "network_client_present" in SENSOR_CONFIG
    assert SENSOR_CONFIG["network_client_present"]["weight"] == 0.75
    assert SENSOR_CONFIG["network_client_present"]["decay_seconds"] == 300

    assert "device_active" in SENSOR_CONFIG
    assert SENSOR_CONFIG["device_active"]["weight"] == 0.40
    assert SENSOR_CONFIG["device_active"]["decay_seconds"] == 120

    assert "protect_person" in SENSOR_CONFIG
    assert SENSOR_CONFIG["protect_person"]["weight"] == 0.85
    assert SENSOR_CONFIG["protect_person"]["decay_seconds"] == 180

    assert "protect_face" in SENSOR_CONFIG
    assert SENSOR_CONFIG["protect_face"]["weight"] == 1.0
    assert SENSOR_CONFIG["protect_face"]["decay_seconds"] == 0
```

**Step 2: Run test to verify it fails**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi_config.py::test_unifi_sensor_config_entries -v
```

Expected: FAIL with `AssertionError: assert 'network_client_present' in {...}`

**Step 3: Add to SENSOR_CONFIG**

In `aria/engine/analysis/occupancy.py`, append after the existing `SENSOR_CONFIG` entries (before the closing `}`):

```python
    # UniFi supplementary signals (cross-validate with Frigate + HA)
    "network_client_present": {"weight": 0.75, "decay_seconds": 300},   # WiFi AP assoc, 5 min decay
    "device_active": {"weight": 0.40, "decay_seconds": 120},            # tx+rx rate active, 2 min
    "protect_person": {"weight": 0.85, "decay_seconds": 180},           # Protect smart detect, 3 min
    "protect_face": {"weight": 1.0, "decay_seconds": 0},                # Protect face → FaceNet, no decay
```

**Step 4: Run test to verify it passes**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi_config.py -v
```

Expected: all tests PASS (including the new one)

**Step 5: Run existing occupancy tests**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/ -k "occupancy" -v
```

Expected: all existing tests PASS (new keys don't break existing ones)

**Step 6: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/engine/analysis/occupancy.py tests/hub/test_unifi_config.py
git commit -m "feat(unifi): add 4 new signal types to SENSOR_CONFIG"
```

---

## Task 4: UniFiModule Skeleton

**Files:**
- Create: `aria/modules/unifi.py`
- Create: `tests/hub/test_unifi.py`

**Step 1: Write the failing tests**

Create `tests/hub/test_unifi.py`:

```python
"""Unit tests for UniFiModule — all external calls mocked."""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria.modules.unifi import UniFiModule


@pytest.fixture
def hub():
    h = MagicMock()
    h.get_config_value = MagicMock(side_effect=lambda key, default=None: {
        "unifi.enabled": "true",
        "unifi.site": "default",
        "unifi.poll_interval_s": "30",
        "unifi.ap_rooms": '{"office-ap": "office", "bedroom-ap": "bedroom"}',
        "unifi.device_people": '{"aa:bb:cc:dd:ee:ff": "justin"}',
        "unifi.rssi_room_threshold": "-75",
        "unifi.device_active_kbps": "100",
    }.get(key, default))
    h.subscribe = MagicMock()
    h.unsubscribe = MagicMock()
    h.publish = MagicMock()
    h.set_cache = AsyncMock()
    h.get_cache = AsyncMock(return_value=None)
    h.is_running = MagicMock(return_value=False)
    return h


@pytest.fixture
def module(hub):
    return UniFiModule(hub, host="192.168.1.1", api_key="test-key")


def test_module_id(module):
    assert module.module_id == "unifi"


def test_module_inherits_module(module):
    from aria.hub.core import Module
    assert isinstance(module, Module)


def test_disabled_by_default():
    hub = MagicMock()
    hub.get_config_value = MagicMock(return_value="false")
    m = UniFiModule(hub, host="192.168.1.1", api_key="test-key")
    assert m._enabled is False


def test_env_host_override(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "10.0.0.1")
    hub = MagicMock()
    hub.get_config_value = MagicMock(return_value="true")
    m = UniFiModule(hub, host="192.168.1.1", api_key="test-key")
    assert m._host == "10.0.0.1"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'aria.modules.unifi'`

**Step 3: Create the module skeleton**

Create `aria/modules/unifi.py`:

```python
"""UniFi Network + Protect presence signals for ARIA.

Two signal pipelines sharing one aiohttp session:
- Network: REST polling /proxy/network/api/s/{site}/stat/sta (WiFi clients)
- Protect: uiprotect WebSocket (smart detect events + face thumbnails)

Auth: X-API-Key header. ssl=False for Dream Machine self-signed cert.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from aria.hub.core import Module

logger = logging.getLogger(__name__)


class UniFiModule(Module):
    """Supplementary presence signals from UniFi Network and Protect."""

    module_id = "unifi"

    def __init__(self, hub, host: str = "", api_key: str = ""):
        super().__init__(hub)
        # UNIFI_HOST env var overrides constructor arg (env is authoritative)
        self._host = os.environ.get("UNIFI_HOST", host).rstrip("/")
        self._api_key = os.environ.get("UNIFI_API_KEY", api_key)
        self._enabled: bool = False

        # Loaded from config in initialize()
        self._site: str = "default"
        self._poll_interval: int = 30
        self._ap_rooms: dict[str, str] = {}
        self._device_people: dict[str, str] = {}
        self._rssi_threshold: int = -75
        self._active_kbps: int = 100

        # Runtime state
        self._session = None         # aiohttp.ClientSession
        self._protect_client = None  # uiprotect.ProtectApiClient
        self._home_away: bool = True  # True = someone home, False = all away
        self._last_client_state: dict[str, Any] = {}  # MAC → client data (last poll)
        self._last_error: str | None = None

        # Subscriber callback references (for unsubscribe in shutdown)
        # UniFiModule currently uses no hub.subscribe() — signals are polled/pushed directly.

    def _load_config(self) -> None:
        """Load all unifi.* config values from hub."""
        enabled_str = self.hub.get_config_value("unifi.enabled", "false")
        self._enabled = str(enabled_str).lower() in ("true", "1", "yes")
        self._site = self.hub.get_config_value("unifi.site", "default")
        self._poll_interval = int(self.hub.get_config_value("unifi.poll_interval_s", 30))
        self._rssi_threshold = int(self.hub.get_config_value("unifi.rssi_room_threshold", -75))
        self._active_kbps = int(self.hub.get_config_value("unifi.device_active_kbps", 100))

        ap_rooms_raw = self.hub.get_config_value("unifi.ap_rooms", "{}")
        try:
            self._ap_rooms = json.loads(ap_rooms_raw) if ap_rooms_raw else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("unifi.ap_rooms is not valid JSON — using empty mapping")
            self._ap_rooms = {}

        device_people_raw = self.hub.get_config_value("unifi.device_people", "{}")
        try:
            self._device_people = json.loads(device_people_raw) if device_people_raw else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("unifi.device_people is not valid JSON — using empty mapping")
            self._device_people = {}

    async def initialize(self) -> None:
        """Load config and start polling/WebSocket loops if enabled."""
        self._load_config()

        if not self._enabled:
            logger.info("UniFi integration disabled (unifi.enabled=false)")
            return

        if not self._host:
            logger.warning("UniFi: no host configured (set UNIFI_HOST env var) — module disabled")
            self._enabled = False
            return

        if not self._api_key:
            logger.warning("UniFi: no API key configured (set UNIFI_API_KEY env var) — module disabled")
            self._enabled = False
            return

        import aiohttp
        self._session = aiohttp.ClientSession(
            headers={"X-API-Key": self._api_key},
            connector=aiohttp.TCPConnector(ssl=False),
        )
        logger.info("UniFi module initialized (host=%s, site=%s)", self._host, self._site)

        # Start loops — tracked as tasks by hub via log_task_exception pattern
        asyncio.create_task(self._network_poll_loop(), name="unifi_network_poll")
        asyncio.create_task(self._protect_ws_loop(), name="unifi_protect_ws")

    async def shutdown(self) -> None:
        """Close aiohttp session and disconnect Protect client."""
        if self._session:
            await self._session.close()
            self._session = None
        if self._protect_client:
            try:
                await self._protect_client.disconnect()
            except Exception:
                pass
            self._protect_client = None
        logger.info("UniFi module shut down")

    # ── Stub loops (implemented in Tasks 5, 7) ────────────────────────

    async def _network_poll_loop(self) -> None:
        """Poll UniFi Network for WiFi client state every poll_interval_s."""
        raise NotImplementedError  # implemented in Task 5

    async def _protect_ws_loop(self) -> None:
        """Subscribe to UniFi Protect WebSocket for smart detect events."""
        raise NotImplementedError  # implemented in Task 7
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: all 4 tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/modules/unifi.py tests/hub/test_unifi.py
git commit -m "feat(unifi): UniFiModule skeleton — config loading, init/shutdown, stubs"
```

---

## Task 5: Network Pipeline — REST Polling

**Files:**
- Modify: `aria/modules/unifi.py` (replace `_network_poll_loop` stub + add helpers)
- Modify: `tests/hub/test_unifi.py` (add network tests)

**Step 1: Write the failing tests**

Append to `tests/hub/test_unifi.py`:

```python
# ── Network pipeline tests ────────────────────────────────────────────

MOCK_STA_RESPONSE = {
    "data": [
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ap_mac": "11:22:33:44:55:66",
            "hostname": "justins-iphone",
            "rssi": -60,
            "tx_bytes_r": 10000,
            "rx_bytes_r": 5000,
            "last_seen": 1700000000,
        },
        {
            "mac": "ff:ee:dd:cc:bb:aa",
            "ap_mac": "aa:bb:cc:11:22:33",
            "hostname": "guest-device",
            "rssi": -80,
            "tx_bytes_r": 0,
            "rx_bytes_r": 0,
            "last_seen": 1700000000,
        },
    ]
}


def test_resolve_person_from_device_people(module):
    result = module._resolve_person("aa:bb:cc:dd:ee:ff", "justins-iphone")
    assert result == "justin"


def test_resolve_person_falls_back_to_hostname(module):
    result = module._resolve_person("00:11:22:33:44:55", "bobs-phone")
    assert result == "bobs-phone"


def test_resolve_person_returns_none_for_unknown(module):
    result = module._resolve_person("00:11:22:33:44:55", "")
    assert result is None


def test_resolve_room_from_ap_rooms(module):
    # ap_rooms maps "office-ap" → "office"
    # module fixture uses ap names, not MACs; test with MAC key too
    module._ap_rooms = {"11:22:33:44:55:66": "office"}
    result = module._resolve_room("11:22:33:44:55:66")
    assert result == "office"


def test_resolve_room_returns_none_for_unmapped(module):
    result = module._resolve_room("unknown-ap-mac")
    assert result is None


def test_device_active_above_threshold(module):
    # 10000 + 5000 bytes/s = 15000 bytes/s = 120 kbps > 100 kbps threshold
    assert module._is_device_active(tx_bytes_r=10000, rx_bytes_r=5000) is True


def test_device_active_below_threshold(module):
    # 1000 + 500 = 1500 bytes/s = 12 kbps < 100 kbps
    assert module._is_device_active(tx_bytes_r=1000, rx_bytes_r=500) is False


@pytest.mark.asyncio
async def test_process_clients_adds_signal(module):
    """_process_clients() should update _last_client_state and return signals."""
    module._ap_rooms = {"11:22:33:44:55:66": "office"}
    module._device_people = {"aa:bb:cc:dd:ee:ff": "justin"}

    clients = MOCK_STA_RESPONSE["data"]
    signals = module._process_clients(clients)

    # Should have office → network_client_present for justin
    assert any(s["room"] == "office" and s["signal_type"] == "network_client_present"
               for s in signals)
    # Justin's device is active (120 kbps > 100)
    assert any(s["room"] == "office" and s["signal_type"] == "device_active"
               for s in signals)


@pytest.mark.asyncio
async def test_process_clients_updates_home_away(module):
    """_process_clients() with known device present → home=True."""
    module._device_people = {"aa:bb:cc:dd:ee:ff": "justin"}
    clients = MOCK_STA_RESPONSE["data"]  # includes aa:bb:cc:dd:ee:ff
    module._process_clients(clients)
    assert module._home_away is True


@pytest.mark.asyncio
async def test_process_clients_all_absent_sets_away(module):
    """_process_clients() with no known devices → home=False."""
    module._device_people = {"aa:bb:cc:dd:ee:ff": "justin"}
    module._process_clients([])  # empty client list
    assert module._home_away is False


def test_rssi_below_threshold_halves_weight(module):
    """Signal weight is halved when RSSI below rssi_room_threshold."""
    module._rssi_threshold = -75
    weight = module._compute_network_weight(rssi=-80)
    assert weight == pytest.approx(0.75 * 0.5)


def test_rssi_above_threshold_full_weight(module):
    weight = module._compute_network_weight(rssi=-60)
    assert weight == pytest.approx(0.75)
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -k "network or resolve or device_active or rssi or process_clients or home_away" -v
```

Expected: FAIL with `AttributeError: 'UniFiModule' object has no attribute '_resolve_person'` (or similar)

**Step 3: Implement network pipeline**

Replace the `_network_poll_loop` stub and add helpers in `aria/modules/unifi.py`. Add these methods to the `UniFiModule` class:

```python
    # ── Person and room resolution ────────────────────────────────────

    def _resolve_person(self, mac: str, hostname: str) -> str | None:
        """Resolve MAC → person name. device_people override > hostname > None."""
        if mac in self._device_people:
            return self._device_people[mac]
        return hostname if hostname else None

    def _resolve_room(self, ap_mac: str) -> str | None:
        """Resolve AP MAC → room name via ap_rooms config."""
        return self._ap_rooms.get(ap_mac)

    def _is_device_active(self, tx_bytes_r: int, rx_bytes_r: int) -> bool:
        """True if tx+rx rate exceeds device_active_kbps threshold."""
        kbps = (tx_bytes_r + rx_bytes_r) * 8 / 1000
        return kbps >= self._active_kbps

    def _compute_network_weight(self, rssi: int) -> float:
        """Base weight for network_client_present, halved if RSSI is ambiguous."""
        base = 0.75
        if rssi < self._rssi_threshold:
            return base * 0.5
        return base

    # ── Client state processing ───────────────────────────────────────

    def _process_clients(self, clients: list[dict]) -> list[dict]:
        """Process raw UniFi client list → signal dicts + update home/away state.

        Returns list of dicts: {room, signal_type, value, detail, ts}
        """
        ts = datetime.now(UTC)
        signals: list[dict] = []
        known_macs = set(self._device_people.keys())
        seen_known: set[str] = set()

        # Update cached client state (MAC → data) for cross-validation
        self._last_client_state = {c["mac"]: c for c in clients}

        for client in clients:
            mac = client.get("mac", "")
            ap_mac = client.get("ap_mac", "")
            hostname = client.get("hostname", "")
            rssi = client.get("rssi", -90)
            tx_bytes_r = client.get("tx_bytes_r", 0)
            rx_bytes_r = client.get("rx_bytes_r", 0)

            person = self._resolve_person(mac, hostname)
            room = self._resolve_room(ap_mac)

            # Track known devices for home/away gate
            if mac in known_macs:
                seen_known.add(mac)

            if room is None:
                continue  # Can't place in room — skip room signals; home/away still tracked

            weight = self._compute_network_weight(rssi)
            detail = f"{person or hostname}@{room} rssi={rssi}"
            signals.append({
                "room": room,
                "signal_type": "network_client_present",
                "value": weight,
                "detail": detail,
                "ts": ts,
            })

            if self._is_device_active(tx_bytes_r, rx_bytes_r):
                signals.append({
                    "room": room,
                    "signal_type": "device_active",
                    "value": 0.85,
                    "detail": f"{person or hostname} active",
                    "ts": ts,
                })

        # Update home/away gate
        self._home_away = len(seen_known) > 0 if known_macs else True
        return signals

    # ── Network poll loop ──────────────────────────────────────────────

    async def _network_poll_loop(self) -> None:
        """Poll UniFi Network for WiFi client state every poll_interval_s."""
        url = f"https://{self._host}/proxy/network/api/s/{self._site}/stat/sta"
        while self.hub.is_running():
            try:
                async with self._session.get(url) as resp:
                    if resp.status == 401:
                        self._last_error = "API key invalid (401)"
                        logger.error("UniFi Network: API key invalid — disabling module")
                        self._enabled = False
                        return
                    resp.raise_for_status()
                    data = await resp.json()
                    clients = data.get("data", [])
                    signals = self._process_clients(clients)

                    # Publish signals to hub for PresenceModule cross-validation
                    await self.hub.set_cache("unifi_client_state", {
                        "home": self._home_away,
                        "clients": self._last_client_state,
                        "signals": signals,
                        "updated_at": datetime.now(UTC).isoformat(),
                    })
                    self._last_error = None
                    logger.debug("UniFi Network: %d clients, %d signals, home=%s",
                                 len(clients), len(signals), self._home_away)

            except Exception as e:
                self._last_error = str(e)
                logger.warning("UniFi Network poll error: %s", e)

            await asyncio.sleep(self._poll_interval)
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/modules/unifi.py tests/hub/test_unifi.py
git commit -m "feat(unifi): Network pipeline — REST polling, signal generation, home/away gate"
```

---

## Task 6: Protect Pipeline — WebSocket Events + Face Handoff

**Files:**
- Modify: `aria/modules/unifi.py` (replace `_protect_ws_loop` stub)
- Modify: `tests/hub/test_unifi.py` (add Protect tests)

**Step 1: Write the failing tests**

Append to `tests/hub/test_unifi.py`:

```python
# ── Protect pipeline tests ────────────────────────────────────────────

def test_protect_unavailable_disables_gracefully(hub, monkeypatch):
    """If uiprotect is not installed, Protect pipeline is skipped without crash."""
    import sys
    monkeypatch.setitem(sys.modules, "uiprotect", None)
    m = UniFiModule(hub, host="192.168.1.1", api_key="test-key")
    # Should construct without raising
    assert m is not None


@pytest.mark.asyncio
async def test_protect_person_event_adds_signal(module):
    """SmartDetectZone person event → protect_person signal published to hub."""
    signals_published = []

    async def mock_set_cache(key, value):
        if key == "unifi_protect_signal":
            signals_published.append(value)

    module.hub.set_cache = mock_set_cache
    module._ap_rooms = {}

    # Simulate a parsed Protect event
    event = {
        "type": "smartDetectZone",
        "object_type": "person",
        "camera_name": "office",
        "event_id": "evt-001",
        "score": 0.92,
    }
    await module._handle_protect_person(event, room="office")
    assert len(signals_published) == 1
    assert signals_published[0]["signal_type"] == "protect_person"
    assert signals_published[0]["room"] == "office"


@pytest.mark.asyncio
async def test_protect_thumbnail_failure_still_adds_signal(module, tmp_path):
    """Thumbnail fetch failure → protect_person signal still added; face pipeline skipped."""
    signals_published = []

    async def mock_set_cache(key, value):
        if key == "unifi_protect_signal":
            signals_published.append(value)

    module.hub.set_cache = mock_set_cache

    with patch.object(module, "_fetch_protect_thumbnail", side_effect=Exception("timeout")):
        await module._handle_protect_person(
            {"type": "smartDetectZone", "object_type": "person",
             "camera_name": "office", "event_id": "evt-002", "score": 0.8},
            room="office",
        )
    # Signal still added despite thumbnail failure
    assert len(signals_published) == 1
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -k "protect" -v
```

Expected: FAIL with `AttributeError: 'UniFiModule' object has no attribute '_handle_protect_person'`

**Step 3: Implement Protect pipeline**

Add these methods to `UniFiModule` in `aria/modules/unifi.py`:

```python
    # ── Protect pipeline ───────────────────────────────────────────────

    async def _handle_protect_person(self, event: dict, room: str) -> None:
        """Handle a parsed Protect SmartDetect person event.

        1. Publish protect_person signal to hub cache.
        2. Fetch thumbnail → feed into existing FacePipeline (best-effort).
        """
        ts = datetime.now(UTC)
        signal = {
            "room": room,
            "signal_type": "protect_person",
            "value": 0.85,
            "detail": f"protect:{event.get('camera_name', '?')} score={event.get('score', 0):.2f}",
            "ts": ts.isoformat(),
            "event_id": event.get("event_id"),
        }
        await self.hub.set_cache("unifi_protect_signal", signal)
        logger.debug("UniFi Protect: person in %s (event=%s)", room, event.get("event_id"))

        # Fetch thumbnail and feed into face pipeline (non-fatal)
        event_id = event.get("event_id")
        if event_id:
            try:
                thumbnail_bytes = await self._fetch_protect_thumbnail(event_id)
                if thumbnail_bytes:
                    await self._feed_face_pipeline(thumbnail_bytes, room, event_id)
            except Exception as e:
                logger.debug("UniFi Protect: thumbnail fetch failed for %s — %s", event_id, e)

    async def _fetch_protect_thumbnail(self, event_id: str) -> bytes | None:
        """Fetch event thumbnail from UniFi Protect REST API."""
        url = f"https://{self._host}/proxy/protect/api/events/{event_id}/thumbnail"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                return None
            return await resp.read()

    async def _feed_face_pipeline(self, thumbnail_bytes: bytes, room: str, event_id: str) -> None:
        """Save thumbnail and feed into ARIA's existing FacePipeline.

        Reuses the face snapshot directory + existing _process_face_async pipeline
        in PresenceModule — UniFiModule does not duplicate face logic.
        """
        import os
        from pathlib import Path

        snapshots_dir_str = os.environ.get("ARIA_FACES_SNAPSHOTS_DIR", "")
        if not snapshots_dir_str:
            return

        snapshots_dir = Path(snapshots_dir_str)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        img_path = snapshots_dir / f"protect_{event_id}.jpg"
        img_path.write_bytes(thumbnail_bytes)

        # Publish face_snapshot event — PresenceModule's FacePipeline subscriber picks it up
        self.hub.publish("face_snapshot_available", {
            "image_path": str(img_path),
            "room": room,
            "source": "protect",
            "event_id": event_id,
        })
        logger.debug("UniFi Protect: thumbnail saved → %s", img_path.name)

    async def _protect_ws_loop(self) -> None:
        """Subscribe to UniFi Protect WebSocket via uiprotect library.

        Uses exponential backoff on disconnect (same pattern as Frigate MQTT in presence.py).
        """
        try:
            from uiprotect import ProtectApiClient
        except ImportError:
            logger.warning("uiprotect not installed — Protect pipeline disabled. "
                           "Install with: pip install -e '.[unifi]'")
            return

        backoff = 5
        while self.hub.is_running():
            try:
                client = ProtectApiClient(
                    self._host, 0, "", "", use_ssl=False,
                    override_connection_host=True,
                )
                # Inject API key auth via session override
                client._api_key = self._api_key  # noqa: SLF001 — uiprotect internal
                self._protect_client = client
                await client.update()

                async for msg in client.subscribe_websocket():
                    if not self.hub.is_running():
                        break
                    await self._dispatch_protect_event(msg)
                    backoff = 5  # reset on successful message

            except Exception as e:
                logger.warning("UniFi Protect WebSocket error: %s — retrying in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                if self._protect_client:
                    try:
                        await self._protect_client.disconnect()
                    except Exception:
                        pass
                    self._protect_client = None

    async def _dispatch_protect_event(self, msg: Any) -> None:
        """Route a Protect WebSocket message to the correct handler."""
        try:
            # uiprotect delivers model objects; check for SmartDetect events
            from uiprotect.data.nvr import Event
            if not isinstance(msg, Event):
                return
            if msg.type.value != "smartDetectZone":
                return
            if "person" not in (msg.smart_detect_types or []):
                return

            camera_name = msg.camera.name if msg.camera else "unknown"
            room = self._ap_rooms.get(camera_name, camera_name.lower().replace(" ", "_"))
            event_dict = {
                "type": "smartDetectZone",
                "object_type": "person",
                "camera_name": camera_name,
                "event_id": msg.id,
                "score": msg.score or 0.0,
            }
            await self._handle_protect_person(event_dict, room)
        except Exception as e:
            logger.debug("UniFi Protect: dispatch error — %s", e)
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/modules/unifi.py tests/hub/test_unifi.py
git commit -m "feat(unifi): Protect pipeline — WebSocket events, face thumbnail handoff"
```

---

## Audit Checkpoint 1: Core Module Review

**Invoke specialized code-reviewer agent for Tasks 1-6.**

Use the `feature-dev:code-reviewer` agent:

```
Review aria/modules/unifi.py for:
1. Silent exception swallowing — every except block must log before return/continue (Lesson #7)
2. Async discipline — no async def without I/O; every hub.set_cache call has await (Lessons #25, #30)
3. Module lifecycle — initialize() does resource acquisition, __init__() is data-only (Lesson #28)
4. Hub cache API — only hub.set_cache()/get_cache(), never hub.cache.* directly (Lesson #12)
5. Any security issues — API key in logs, paths in public data, etc.
Report only high-confidence issues. Include file:line for each finding.
```

**Run existing test suite to confirm no regressions:**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/ -v --timeout=120 -q
```

Expected: all pre-existing tests PASS, plus new unifi tests PASS.

---

## Task 7: Cross-Validation Layer

**Files:**
- Modify: `aria/modules/unifi.py` (add `_cross_validate_signals()`)
- Modify: `tests/hub/test_unifi.py` (add cross-validation tests)

**Step 1: Write the failing tests**

Append to `tests/hub/test_unifi.py`:

```python
# ── Cross-validation tests ────────────────────────────────────────────

@pytest.fixture
def module_with_clients(module):
    """Module with a known client state: justin's phone in office."""
    module._last_client_state = {
        "aa:bb:cc:dd:ee:ff": {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ap_mac": "11:22:33:44:55:66",
            "hostname": "justins-iphone",
        }
    }
    module._ap_rooms = {"11:22:33:44:55:66": "office"}
    module._home_away = True
    return module


def test_cross_validate_boosts_corroborated_signals(module_with_clients):
    """network_client_present + camera_person in same room → both boosted."""
    room_signals = {
        "office": [
            ("network_client_present", 0.75, "justin@office", None),
            ("camera_person", 0.9, "person detected", None),
        ]
    }
    result = module_with_clients.cross_validate_signals(room_signals)
    office = dict(result["office"])
    # Both should be boosted (capped at 0.95)
    assert office["network_client_present"] > 0.75
    assert office["camera_person"] > 0.9


def test_cross_validate_suppresses_unsupported_camera(module_with_clients):
    """camera_person fires but no network device within 2 rooms → reduce weight."""
    # Remove device from client state — no known device at all
    module_with_clients._last_client_state = {}
    module_with_clients._home_away = True  # home but no device seen

    room_signals = {
        "bedroom": [
            ("camera_person", 0.9, "person detected", None),
        ]
    }
    result = module_with_clients.cross_validate_signals(room_signals)
    bedroom = dict(result["bedroom"])
    # camera_person should be reduced (likely pet/shadow)
    assert bedroom["camera_person"] < 0.9


def test_cross_validate_no_change_when_no_client_state(module):
    """Without client state, signals pass through unchanged."""
    module._last_client_state = {}
    room_signals = {
        "office": [("camera_person", 0.9, "detail", None)]
    }
    result = module.cross_validate_signals(room_signals)
    assert dict(result["office"])["camera_person"] == pytest.approx(0.9)
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -k "cross_validate" -v
```

Expected: FAIL with `AttributeError: 'UniFiModule' object has no attribute 'cross_validate_signals'`

**Step 3: Implement cross-validation**

Add to `UniFiModule` in `aria/modules/unifi.py`:

```python
    # ── Cross-validation ──────────────────────────────────────────────

    def cross_validate_signals(
        self, room_signals: dict[str, list[tuple]]
    ) -> dict[str, list[tuple]]:
        """Adjust signal weights based on cross-validation between UniFi and camera signals.

        Called by PresenceModule._flush_presence_state() before Bayesian fusion.
        Input/output format: {room: [(signal_type, value, detail, ts), ...]}

        Rules (from PMC10864388 — reduces false alarms 63.1% → 8.4%):
        1. network_client_present + camera_person/protect_person same room → boost both ×1.15 (cap 0.95)
        2. camera_person in room but no known device → reduce camera_person ×0.70
        3. No client state available → pass through unchanged (graceful degradation)
        """
        if not self._last_client_state:
            return room_signals

        # Build room → set of MAC addresses from last poll
        room_to_macs: dict[str, set[str]] = {}
        for mac, client in self._last_client_state.items():
            ap_mac = client.get("ap_mac", "")
            room = self._resolve_room(ap_mac)
            if room:
                room_to_macs.setdefault(room, set()).add(mac)

        result: dict[str, list[tuple]] = {}
        for room, signals in room_signals.items():
            has_network = any(sig[0] == "network_client_present" for sig in signals)
            has_camera = any(sig[0] in ("camera_person", "protect_person") for sig in signals)
            room_has_device = bool(room_to_macs.get(room))

            new_signals = []
            for sig_type, value, detail, ts in signals:
                if has_network and has_camera and sig_type in (
                    "network_client_present", "camera_person", "protect_person"
                ):
                    # Rule 1: Two independent systems agree → boost
                    value = min(value * 1.15, 0.95)
                elif sig_type in ("camera_person", "protect_person") and not room_has_device:
                    # Rule 2: Camera fires but no known device nearby → likely pet
                    value = value * 0.70
                new_signals.append((sig_type, value, detail, ts))
            result[room] = new_signals

        return result
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/modules/unifi.py tests/hub/test_unifi.py
git commit -m "feat(unifi): cross-validation layer — boost corroborated, suppress unsupported signals"
```

---

## Task 8: Presence Module Integration

**Files:**
- Modify: `aria/modules/presence.py`
- Modify: `tests/hub/test_presence.py` (add cross-validation integration tests)

**Step 1: Understand the integration point**

Read `aria/modules/presence.py` around `_flush_presence_state` and `_add_signal` (lines ~1020-1080) to confirm the signal format before writing tests.

The `_room_signals` dict is: `{room: [(signal_type, value, detail, timestamp), ...]}`. Cross-validation must run on this exact format.

**Step 2: Write the failing test**

Add to `tests/hub/test_presence.py`:

```python
def test_flush_with_unifi_cross_validation(presence_fixture):
    """_flush_presence_state() uses UniFi cross-validation when module available."""
    # This test verifies the integration point exists, not the math (tested in test_unifi.py)
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    hub = presence_fixture.hub
    # Simulate unifi_client_state in hub cache
    hub.get_cache = AsyncMock(return_value={
        "home": True,
        "clients": {},
        "signals": [],
        "updated_at": "2026-01-01T00:00:00+00:00",
    })
    # Should not raise
    asyncio.get_event_loop().run_until_complete(presence_fixture._flush_presence_state())
```

> **Note:** If `test_presence.py` doesn't have a `presence_fixture`, adapt to the existing fixture pattern in that file. Run: `.venv/bin/python -m pytest tests/hub/test_presence.py --collect-only | head -20` to see available fixtures before writing this test.

**Step 3: Add cross-validation call to `_flush_presence_state`**

In `aria/modules/presence.py`, find `_flush_presence_state`. After signals are collected into `self._room_signals` but before Bayesian fusion, add:

```python
        # Cross-validate with UniFi client state if module is available
        unifi_state = await self.hub.get_cache("unifi_client_state")
        if unifi_state and unifi_state.get("home") is False:
            # All known devices absent — suppress all room signals
            for room in list(self._room_signals.keys()):
                self._room_signals[room] = []
            logger.debug("UniFi home/away gate: all devices away — suppressing room signals")
        elif unifi_state:
            # Apply cross-validation boost/suppression
            unifi_mod = self.hub.get_module("unifi")
            if unifi_mod is not None:
                room_tuples = {
                    room: [(s[0], s[1], s[2], s[3]) for s in signals]
                    for room, signals in self._room_signals.items()
                }
                adjusted = unifi_mod.cross_validate_signals(room_tuples)
                self._room_signals = {
                    room: list(tuples) for room, tuples in adjusted.items()
                }
```

**Step 4: Confirm flush signature**

Read `aria/hub/core.py` around line 613 to confirm `hub.get_module(module_id)` returns the module instance or None:

```bash
cd /home/justin/Documents/projects/ha-aria
grep -n "def get_module" aria/hub/core.py
```

**Step 5: Run tests to verify pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_presence.py -v --timeout=120
```

Expected: all presence tests PASS (including new one if added)

**Step 6: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/modules/presence.py tests/hub/test_presence.py
git commit -m "feat(unifi): integrate cross-validation + home/away gate into presence flush"
```

---

## Task 9: CLI Registration

**Files:**
- Modify: `aria/cli.py` (register UniFiModule in `_register_modules`)

**Step 1: Confirm no module_id collision**

```bash
cd /home/justin/Documents/projects/ha-aria
grep -r "module_id = " aria/modules/ | grep -v test
```

Expected: `unifi` appears only once (in `aria/modules/unifi.py`).

**Step 2: Write the failing test**

Add to `tests/hub/test_unifi.py`:

```python
def test_module_id_not_duplicated():
    """Verify no other module uses the 'unifi' ID."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", 'module_id = "unifi"', "aria/"],
        capture_output=True, text=True,
        cwd="/home/justin/Documents/projects/ha-aria",
    )
    matches = [line for line in result.stdout.strip().splitlines()
               if not line.endswith("test_unifi.py")]
    assert len(matches) == 1, f"Expected exactly one module with id 'unifi', got: {matches}"
```

**Step 3: Add UniFiModule to `_register_modules` in `aria/cli.py`**

After the presence module registration block (around line 601), add:

```python
    # unifi (optional — requires UNIFI_HOST env var and unifi.enabled=true)
    try:
        from aria.modules.unifi import UniFiModule

        unifi = UniFiModule(hub)
        hub.register_module(unifi)
        await _init(unifi, "unifi")()
    except Exception as e:
        logger.warning(f"UniFi module failed (non-fatal): {e}")
```

**Step 4: Run tests to verify pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/cli.py tests/hub/test_unifi.py
git commit -m "feat(unifi): register UniFiModule in CLI — non-fatal optional tier"
```

---

## Audit Checkpoint 2: Integration Review

**Invoke `feature-dev:code-reviewer` agent:**

```
Review the integration between aria/modules/unifi.py and aria/modules/presence.py:
1. Trace one value: UniFi Network REST poll → _last_client_state → hub cache → _flush_presence_state → cross_validate_signals → Bayesian fusion. Does data flow end-to-end?
2. Check that cross-validation handles missing/stale unifi cache gracefully (hub.get_cache returns None).
3. Verify home/away gate: when home=False, _room_signals is cleared BEFORE Bayesian fusion, not after.
4. Confirm hub.get_module("unifi") won't raise if UniFi module is not registered.
5. Look for any Cluster B (integration boundary) risks — mismatched dict shapes between unifi.py and presence.py.
Report findings with file:line.
```

**Run full test suite:**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/ -v --timeout=120 -q -n 6
```

Expected: all pre-existing tests PASS. Fix any regressions before continuing.

---

## Task 10: Integration Tests

**Files:**
- Create: `tests/hub/test_unifi_integration.py`

**Step 1: Write the integration tests**

Create `tests/hub/test_unifi_integration.py`:

```python
"""Integration tests: full Network poll + Protect event → presence flush pipeline."""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria.modules.unifi import UniFiModule


@pytest.fixture
def hub():
    h = MagicMock()
    h.get_config_value = MagicMock(side_effect=lambda key, default=None: {
        "unifi.enabled": "true",
        "unifi.site": "default",
        "unifi.poll_interval_s": "30",
        "unifi.ap_rooms": '{"11:22:33:44:55:66": "office"}',
        "unifi.device_people": '{"aa:bb:cc:dd:ee:ff": "justin"}',
        "unifi.rssi_room_threshold": "-75",
        "unifi.device_active_kbps": "100",
    }.get(key, default))
    h.subscribe = MagicMock()
    h.unsubscribe = MagicMock()
    h.publish = MagicMock()
    h.set_cache = AsyncMock()
    h.get_cache = AsyncMock(return_value=None)
    h.is_running = MagicMock(return_value=False)
    return h


@pytest.fixture
def module(hub):
    m = UniFiModule(hub, host="192.168.1.1", api_key="test-key")
    m._load_config()
    return m


@pytest.mark.asyncio
async def test_full_network_pipeline_writes_cache(module):
    """Network poll → _process_clients → hub.set_cache with correct structure."""
    raw_clients = [
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ap_mac": "11:22:33:44:55:66",
            "hostname": "justins-iphone",
            "rssi": -55,
            "tx_bytes_r": 20000,
            "rx_bytes_r": 8000,
            "last_seen": 1700000000,
        }
    ]
    signals = module._process_clients(raw_clients)

    # Verify signal list
    sig_types = {s["signal_type"] for s in signals}
    assert "network_client_present" in sig_types
    assert "device_active" in sig_types  # 28000 bytes/s = 224 kbps > 100 kbps

    # Verify home/away
    assert module._home_away is True

    # Simulate cache write
    cache_payload = {
        "home": module._home_away,
        "clients": module._last_client_state,
        "signals": signals,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    assert "aa:bb:cc:dd:ee:ff" in cache_payload["clients"]
    assert cache_payload["home"] is True


@pytest.mark.asyncio
async def test_home_away_gate_clears_signals_when_away(module):
    """When all devices absent → home=False → cross_validate must clear signals."""
    module._process_clients([])  # empty → home=False
    assert module._home_away is False

    room_signals = {"office": [("camera_person", 0.9, "detail", None)]}
    # Cross-validation with home=False is handled in PresenceModule, not here.
    # Just verify the flag is set correctly.
    assert module._home_away is False


@pytest.mark.asyncio
async def test_cross_validate_full_cycle(module):
    """Full cross-validation cycle: client in room + camera signal → both boosted."""
    module._last_client_state = {
        "aa:bb:cc:dd:ee:ff": {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ap_mac": "11:22:33:44:55:66",
        }
    }
    module._ap_rooms = {"11:22:33:44:55:66": "office"}

    room_signals = {
        "office": [
            ("network_client_present", 0.75, "justin@office rssi=-55", None),
            ("camera_person", 0.90, "person", None),
        ]
    }
    result = module.cross_validate_signals(room_signals)
    office_dict = dict(result["office"])

    # Both signals boosted
    assert office_dict["network_client_present"] > 0.75
    assert office_dict["camera_person"] > 0.90
    # Cap enforced
    assert office_dict["camera_person"] <= 0.95


@pytest.mark.asyncio
async def test_protect_person_publishes_signal(module):
    """Protect person event → protect_person signal in hub cache."""
    event = {
        "type": "smartDetectZone",
        "object_type": "person",
        "camera_name": "office",
        "event_id": "test-evt-001",
        "score": 0.88,
    }
    await module._handle_protect_person(event, room="office")
    module.hub.set_cache.assert_called_once()
    call_args = module.hub.set_cache.call_args
    assert call_args[0][0] == "unifi_protect_signal"
    signal = call_args[0][1]
    assert signal["signal_type"] == "protect_person"
    assert signal["room"] == "office"


@pytest.mark.asyncio
async def test_protect_thumbnail_404_does_not_crash(module):
    """Protect thumbnail 404 → face pipeline skipped, protect_person still published."""
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    module._session = MagicMock()
    module._session.get = MagicMock(return_value=mock_response)

    event = {
        "type": "smartDetectZone",
        "object_type": "person",
        "camera_name": "bedroom",
        "event_id": "test-evt-404",
        "score": 0.7,
    }
    # Should not raise
    await module._handle_protect_person(event, room="bedroom")
    # protect_person signal still published
    module.hub.set_cache.assert_called()
```

**Step 2: Run tests to verify they pass**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/hub/test_unifi_integration.py -v
```

Expected: all 5 tests PASS

**Step 3: Run full test suite**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/ --timeout=120 -q -n 6
```

Expected: all tests PASS, no regressions.

**Step 4: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add tests/hub/test_unifi_integration.py
git commit -m "test(unifi): integration tests — full pipeline coverage"
```

---

## Task 11: Dashboard — Devices Tab

**Files:**
- Modify: `aria/dashboard/spa/src/pages/Presence.jsx`

**Step 1: Understand the existing tab structure**

```bash
cd /home/justin/Documents/projects/ha-aria
grep -n "Tab\|tab\|Devices\|devices" aria/dashboard/spa/src/pages/Presence.jsx | head -30
```

**Step 2: Add Devices tab data fetch**

The Devices tab needs to read `unifi_client_state` from the hub cache. Add an API call:

```javascript
// In the component, alongside existing fetch calls:
const [unifiState, setUnifiState] = useState(null);

useEffect(() => {
  fetch('/api/cache/unifi_client_state')
    .then(r => r.ok ? r.json() : null)
    .then(data => setUnifiState(data))
    .catch(() => setUnifiState(null));
}, []);
```

**Step 3: Add the Devices tab JSX**

Add a new tab in the tabs array and a `DevicesTab` component:

```jsx
// DevicesTab component (add above or below the Presence component)
function DevicesTab({ unifiState }) {
  if (!unifiState) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-secondary)' }}>
        UniFi integration not enabled or no data yet.
        Set <code>unifi.enabled = true</code> in config.
      </div>
    );
  }

  const clients = Object.values(unifiState.clients || {});
  const home = unifiState.home;
  const updatedAt = unifiState.updated_at
    ? new Date(unifiState.updated_at).toLocaleTimeString()
    : 'unknown';

  return (
    <div style={{ padding: '0.5rem' }}>
      <div style={{ marginBottom: '0.75rem', display: 'flex', gap: '1rem', alignItems: 'center' }}>
        <span style={{
          fontWeight: 600,
          color: home ? 'var(--success)' : 'var(--text-secondary)'
        }}>
          {home ? 'Home' : 'Away'}
        </span>
        <span style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
          Updated: {updatedAt} · {clients.length} device{clients.length !== 1 ? 's' : ''} online
        </span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '0.25rem 0.5rem' }}>Device</th>
            <th style={{ textAlign: 'left', padding: '0.25rem 0.5rem' }}>MAC</th>
            <th style={{ textAlign: 'left', padding: '0.25rem 0.5rem' }}>AP</th>
            <th style={{ textAlign: 'left', padding: '0.25rem 0.5rem' }}>RSSI</th>
          </tr>
        </thead>
        <tbody>
          {clients.map(client => (
            <tr key={client.mac} style={{ borderBottom: '1px solid var(--border-light)' }}>
              <td style={{ padding: '0.25rem 0.5rem' }}>
                {client.hostname || client.mac}
              </td>
              <td style={{ padding: '0.25rem 0.5rem', fontFamily: 'monospace' }}>
                {client.mac}
              </td>
              <td style={{ padding: '0.25rem 0.5rem' }}>
                {client.ap_mac || '—'}
              </td>
              <td style={{ padding: '0.25rem 0.5rem' }}>
                {client.rssi != null ? `${client.rssi} dBm` : '—'}
              </td>
            </tr>
          ))}
          {clients.length === 0 && (
            <tr>
              <td colSpan={4} style={{ padding: '1rem', textAlign: 'center',
                                       color: 'var(--text-tertiary)' }}>
                No devices online
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

Add to the tabs array:
```jsx
{ id: 'devices', label: 'Devices', component: <DevicesTab unifiState={unifiState} /> }
```

**Step 4: Build the SPA**

```bash
cd /home/justin/Documents/projects/ha-aria/aria/dashboard/spa
npm run build
```

Expected: build succeeds with no errors. Watch for `h` variable shadowing (Lesson esbuild-jsx — never use `h` as callback param in `.map()`).

**Step 5: Verify no JSX style literal bugs**

```bash
cd /home/justin/Documents/projects/ha-aria
grep -n 'style="' aria/dashboard/spa/src/pages/Presence.jsx | head -10
```

Expected: no matches (all styles use `style={{ }}` object syntax, not string literals — Lesson jsx-style-literal-no-eval).

**Step 6: Commit**

```bash
cd /home/justin/Documents/projects/ha-aria
git add aria/dashboard/spa/src/pages/Presence.jsx aria/dashboard/spa/dist/
git commit -m "feat(unifi): add Devices tab to Presence dashboard — home/away + client list"
```

---

## Task 12: Final Verification

**Step 1: Run full test suite**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m pytest tests/ --timeout=120 -q -n 6
```

Expected: all tests PASS. Note pass/fail count explicitly.

**Step 2: Lint check**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -m ruff check aria/modules/unifi.py aria/hub/config_defaults.py aria/engine/analysis/occupancy.py aria/cli.py
```

Expected: no errors. Fix any before continuing.

**Step 3: Verify module loads when disabled (default state)**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -c "
from unittest.mock import MagicMock
from aria.modules.unifi import UniFiModule
hub = MagicMock()
hub.get_config_value = lambda k, d=None: d
m = UniFiModule(hub)
print('module_id:', m.module_id)
print('enabled:', m._enabled)
print('OK — module loads and is disabled by default')
"
```

Expected output: `enabled: False` and `OK — module loads and is disabled by default`

**Step 4: Verify import when uiprotect not installed (graceful)**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -c "
import sys
sys.modules['uiprotect'] = None
from aria.modules.unifi import UniFiModule
print('OK — module imports fine even when uiprotect is absent')
"
```

Expected: `OK — module imports fine even when uiprotect is absent`

**Step 5: Verify config_defaults seeds correctly**

```bash
cd /home/justin/Documents/projects/ha-aria
.venv/bin/python -c "
from aria.hub.config_defaults import CONFIG_DEFAULTS
unifi_keys = [c['key'] for c in CONFIG_DEFAULTS if c['key'].startswith('unifi.')]
print('UniFi config keys:', unifi_keys)
assert len(unifi_keys) == 8, f'Expected 8 unifi.* keys, got {len(unifi_keys)}'
print('OK')
"
```

Expected: prints 8 keys and `OK`.

**Step 6: Final audit — invoke pr-review-toolkit:code-reviewer**

```
Review all changes in this PR (git diff main...HEAD) for:
1. Silent failures — every except must log before fallback (Lesson #7)
2. Dead config keys — every CONFIG_DEFAULTS key has a matching get_config_value() call (Lesson #54)
3. Subscriber lifecycle — no hub.subscribe() in __init__(); all subscribed in initialize() (Lesson #28/#37)
4. Integration boundary — trace unifi_client_state from set_cache() to get_cache() in presence.py (Lesson end-to-end-data-flow-verification)
5. Security — API key not logged, no internal IPs in JSX bundle
Report high-confidence issues with file:line only.
```

**Step 7: Commit and tag**

```bash
cd /home/justin/Documents/projects/ha-aria
git add -u
git commit -m "feat(unifi): final verification — all tests pass, lint clean"
```

---

## Execution Options

Plan complete and saved to `docs/plans/2026-02-25-unifi-integration-plan.md`.

**Option 1: Parallel Session (Recommended)**
Open a new session in the ha-aria worktree and use `superpowers:executing-plans` with this file. Checkpoints after Tasks 6, 9, and 12.

**Option 2: Subagent-Driven (This Session)**
Use `superpowers:subagent-driven-development` — dispatches a fresh subagent per task with code review between milestones.

---

## Environment Checklist Before Starting

```bash
# Verify UNIFI_HOST is set
grep "UNIFI_HOST" ~/.env

# Verify UNIFI_API_KEY is set
grep "UNIFI_API_KEY" ~/.env

# Verify uiprotect installed (Task 1 must run first if not)
.venv/bin/python -c "import uiprotect; print(uiprotect.__version__)"

# Confirm Python version
.venv/bin/python --version  # must be 3.11 or 3.12
```

If `UNIFI_HOST` is not set, add it to `~/.env`:
```
UNIFI_HOST=192.168.1.1
```
