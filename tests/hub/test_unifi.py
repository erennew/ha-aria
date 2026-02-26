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
