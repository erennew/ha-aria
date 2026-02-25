"""Tests for UniFi config defaults registration."""

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
