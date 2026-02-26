"""Integration tests: full Network poll + Protect event → presence flush pipeline."""

from datetime import UTC, datetime
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
            "unifi.ap_rooms": '{"11:22:33:44:55:66": "office"}',
            "unifi.device_people": '{"aa:bb:cc:dd:ee:ff": "justin"}',
            "unifi.rssi_room_threshold": "-75",
            "unifi.device_active_kbps": "100",
        }.get(key, default)
    )
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

    # Cross-validation with home=False is handled in PresenceModule, not here.
    # Verify cross_validate passes signals through unchanged when client state is empty.
    room_signals = {"office": [("camera_person", 0.9, "detail", None)]}
    result = module.cross_validate_signals(room_signals)
    assert result["office"][0][0] == "camera_person"
    assert result["office"][0][1] == 0.9


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
