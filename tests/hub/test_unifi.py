"""Unit tests for UniFiModule — all external calls mocked."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aria.modules.unifi import UniFiModule


@pytest.fixture
def hub():
    h = MagicMock()
    h.get_config_value = MagicMock(
        side_effect=lambda key, default=None: {
            "unifi.enabled": "true",
            "unifi.site": "default",
            "unifi.poll_interval_s": "30",
            "unifi.ap_rooms": '{"office-ap": "office", "bedroom-ap": "bedroom"}',
            "unifi.device_people": '{"aa:bb:cc:dd:ee:ff": "justin"}',
            "unifi.rssi_room_threshold": "-75",
            "unifi.device_active_kbps": "100",
        }.get(key, default)
    )
    h.subscribe = MagicMock()
    h.unsubscribe = MagicMock()
    h.publish = AsyncMock()
    h.set_cache = AsyncMock()
    h.get_cache = AsyncMock(return_value=None)
    h.is_running = MagicMock(return_value=False)
    return h


@pytest.fixture
def module(hub):
    m = UniFiModule(hub, host="192.168.1.1", api_key="test-key")
    m._load_config()
    return m


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
    assert any(s["room"] == "office" and s["signal_type"] == "network_client_present" for s in signals)
    # Justin's device is active (120 kbps > 100)
    assert any(s["room"] == "office" and s["signal_type"] == "device_active" for s in signals)


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
    assert signals_published
    assert signals_published[0]["signal_type"] == "protect_person"
    assert signals_published[0]["room"] == "office"


@pytest.mark.asyncio
async def test_protect_thumbnail_failure_still_adds_signal(module, tmp_path):
    """Thumbnail fetch failure → protect_person signal still added; face pipeline skipped."""
    from unittest.mock import patch

    signals_published = []

    async def mock_set_cache(key, value):
        if key == "unifi_protect_signal":
            signals_published.append(value)

    module.hub.set_cache = mock_set_cache

    with patch.object(module, "_fetch_protect_thumbnail", side_effect=Exception("timeout")):
        await module._handle_protect_person(
            {
                "type": "smartDetectZone",
                "object_type": "person",
                "camera_name": "office",
                "event_id": "evt-002",
                "score": 0.8,
            },
            room="office",
        )
    # Signal still added despite thumbnail failure
    assert signals_published


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
    """camera_person fires in a room with no network device → reduce weight."""
    # Device is in office (via module_with_clients fixture), camera fires in bedroom.
    # No device seen in bedroom → likely pet/shadow.

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
    room_signals = {"office": [("camera_person", 0.9, "detail", None)]}
    result = module.cross_validate_signals(room_signals)
    assert dict(result["office"])["camera_person"] == pytest.approx(0.9)


def test_module_id_not_duplicated():
    """Verify no other module uses the 'unifi' ID."""
    import subprocess
    from pathlib import Path

    # Use the repo root that contains this worktree's aria/ package
    repo_root = Path(__file__).parent.parent.parent
    result = subprocess.run(
        ["grep", "-r", 'module_id = "unifi"', "aria/"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    matches = [line for line in result.stdout.strip().splitlines() if not line.endswith("test_unifi.py")]
    assert len(matches) == 1, f"Expected exactly one module with id 'unifi', got: {matches}"
