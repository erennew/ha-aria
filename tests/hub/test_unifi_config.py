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
