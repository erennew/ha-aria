"""Known-answer tests for DiscoveryModule.

Validates entity discovery count, classification tiers, and golden snapshot
stability against deterministic mock HA data.
"""

import pytest

from aria.modules.discovery import DiscoveryModule
from tests.integration.known_answer.conftest import golden_compare

# Deterministic HA discovery output (matches bin/discover.py output format)
MOCK_DISCOVERY_OUTPUT = {
    "entity_count": 6,
    "device_count": 3,
    "area_count": 3,
    "ha_version": "2024.1.0",
    "timestamp": "2025-01-01T00:00:00",
    "entities": {
        "light.living_room": {
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {"friendly_name": "Living Room Light"},
            "friendly_name": "Living Room Light",
            "device_id": "dev_001",
            "area_id": None,
            "domain": "light",
            "device_class": None,
            "unit_of_measurement": None,
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
        "sensor.temperature": {
            "entity_id": "sensor.temperature",
            "state": "22.5",
            "attributes": {
                "friendly_name": "Temperature",
                "unit_of_measurement": "\u00b0C",
                "device_class": "temperature",
            },
            "friendly_name": "Temperature",
            "device_id": "dev_002",
            "area_id": None,
            "domain": "sensor",
            "device_class": "temperature",
            "unit_of_measurement": "\u00b0C",
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
        "binary_sensor.motion": {
            "entity_id": "binary_sensor.motion",
            "state": "off",
            "attributes": {
                "friendly_name": "Motion Sensor",
                "device_class": "motion",
            },
            "friendly_name": "Motion Sensor",
            "device_id": "dev_003",
            "area_id": None,
            "domain": "binary_sensor",
            "device_class": "motion",
            "unit_of_measurement": None,
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
        "switch.smart_plug": {
            "entity_id": "switch.smart_plug",
            "state": "on",
            "attributes": {"friendly_name": "Smart Plug"},
            "friendly_name": "Smart Plug",
            "device_id": "dev_001",
            "area_id": None,
            "domain": "switch",
            "device_class": None,
            "unit_of_measurement": None,
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
        "automation.morning_lights": {
            "entity_id": "automation.morning_lights",
            "state": "on",
            "attributes": {"friendly_name": "Morning Lights"},
            "friendly_name": "Morning Lights",
            "device_id": None,
            "area_id": None,
            "domain": "automation",
            "device_class": None,
            "unit_of_measurement": None,
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
        "update.hacs": {
            "entity_id": "update.hacs",
            "state": "off",
            "attributes": {"friendly_name": "HACS Update"},
            "friendly_name": "HACS Update",
            "device_id": None,
            "area_id": None,
            "domain": "update",
            "device_class": None,
            "unit_of_measurement": None,
            "last_changed": None,
            "last_updated": None,
            "labels": [],
            "disabled": False,
            "hidden": False,
            "icon": None,
        },
    },
    "devices": {
        "dev_001": {
            "device_id": "dev_001",
            "name": "Living Room Hub",
            "area_id": "area_living",
            "manufacturer": None,
            "model": None,
            "via_device_id": None,
        },
        "dev_002": {
            "device_id": "dev_002",
            "name": "Climate Sensor",
            "area_id": "area_bedroom",
            "manufacturer": None,
            "model": None,
            "via_device_id": None,
        },
        "dev_003": {
            "device_id": "dev_003",
            "name": "Motion Detector",
            "area_id": "area_hallway",
            "manufacturer": None,
            "model": None,
            "via_device_id": None,
        },
    },
    "areas": {
        "area_living": {"area_id": "area_living", "name": "Living Room"},
        "area_bedroom": {"area_id": "area_bedroom", "name": "Bedroom"},
        "area_hallway": {"area_id": "area_hallway", "name": "Hallway"},
    },
    "capabilities": {},
    "integrations": [],
}


@pytest.fixture
async def discovery_module(hub, monkeypatch):
    """Create a DiscoveryModule with mocked discovery subprocess."""
    # Patch Path.exists within the discovery module — DiscoveryModule.__init__
    # checks that bin/discover.py exists. This is the only Path.exists call in
    # the constructor path, so the broad patch is safe for this test scope.
    monkeypatch.setattr("aria.modules.discovery.Path.exists", lambda self: True)
    module = DiscoveryModule(hub=hub, ha_url="http://test-host:8123", ha_token="test-token")

    # Replace run_discovery to bypass subprocess — directly store results
    async def mock_run_discovery():
        await module._store_discovery_results(MOCK_DISCOVERY_OUTPUT)
        return MOCK_DISCOVERY_OUTPUT

    monkeypatch.setattr(module, "run_discovery", mock_run_discovery)

    # Run discovery to populate cache (use the patched method for consistency)
    await module.run_discovery()
    return module


@pytest.mark.asyncio
async def test_discovery_entity_count(discovery_module, hub):
    """Verify discovered entity count matches mock data."""
    entities_entry = await hub.get_cache("entities")
    assert entities_entry is not None
    entities = entities_entry["data"]
    assert len(entities) == 6, f"Expected 6 entities, got {len(entities)}"

    # Verify all expected entity IDs are present
    expected_ids = {
        "light.living_room",
        "sensor.temperature",
        "binary_sensor.motion",
        "switch.smart_plug",
        "automation.morning_lights",
        "update.hacs",
    }
    assert set(entities.keys()) == expected_ids


@pytest.mark.asyncio
async def test_discovery_device_and_area_count(discovery_module, hub):
    """Verify discovered device and area counts."""
    devices_entry = await hub.get_cache("devices")
    assert devices_entry is not None
    assert len(devices_entry["data"]) == 3

    areas_entry = await hub.get_cache("areas")
    assert areas_entry is not None
    assert len(areas_entry["data"]) == 3


@pytest.mark.asyncio
async def test_classification_tiers(discovery_module, hub):
    """Verify entity classification: automation/update → tier 1 auto-excluded."""
    await discovery_module.run_classification()

    # Direct hub.cache.get_curation() access — no hub.get_curation() public method exists.
    # Justified: curation is a dedicated SQLite table, not a cache category.
    automation_curation = await hub.cache.get_curation("automation.morning_lights")
    assert automation_curation is not None, "automation.morning_lights should have curation"
    assert automation_curation["tier"] == 1, f"automation domain should be tier 1, got {automation_curation['tier']}"
    assert automation_curation["status"] == "auto_excluded"

    # Check update.hacs → tier 1 (update is auto-excluded domain)
    update_curation = await hub.cache.get_curation("update.hacs")
    assert update_curation is not None, "update.hacs should have curation"
    assert update_curation["tier"] == 1, f"update domain should be tier 1, got {update_curation['tier']}"
    assert update_curation["status"] == "auto_excluded"

    # Check light.living_room → tier 3 (general entity, default include)
    light_curation = await hub.cache.get_curation("light.living_room")
    assert light_curation is not None, "light.living_room should have curation"
    assert light_curation["tier"] == 3, f"light domain should be tier 3, got {light_curation['tier']}"
    assert light_curation["status"] == "included"

    # Check sensor.temperature → tier 3 (general entity)
    sensor_curation = await hub.cache.get_curation("sensor.temperature")
    assert sensor_curation is not None
    assert sensor_curation["tier"] == 3
    assert sensor_curation["status"] == "included"

    # Check switch.smart_plug → tier 3 (general entity)
    switch_curation = await hub.cache.get_curation("switch.smart_plug")
    assert switch_curation is not None
    assert switch_curation["tier"] == 3
    assert switch_curation["status"] == "included"

    # Check binary_sensor.motion → tier 3 (general entity, motion device_class
    # but not in PRESENCE_DOMAINS so not tier 2)
    motion_curation = await hub.cache.get_curation("binary_sensor.motion")
    assert motion_curation is not None
    assert motion_curation["tier"] == 3
    assert motion_curation["status"] == "included"


@pytest.mark.asyncio
async def test_golden_snapshot(discovery_module, hub, update_golden):
    """Golden snapshot comparison for discovery + classification output."""
    await discovery_module.run_classification()

    # Build snapshot of all entity curations
    entity_ids = sorted(MOCK_DISCOVERY_OUTPUT["entities"].keys())
    snapshot = {}
    for eid in entity_ids:
        curation = await hub.cache.get_curation(eid)
        if curation:
            # Extract deterministic fields only (exclude timestamps)
            snapshot[eid] = {
                "tier": curation["tier"],
                "status": curation["status"],
                "reason": curation["reason"],
                "auto_classification": curation.get("auto_classification"),
            }

    golden_compare(snapshot, "discovery_classification", update=update_golden)

    # Verify the snapshot has all entities classified
    assert len(snapshot) == 6, f"Expected 6 classified entities, got {len(snapshot)}"
