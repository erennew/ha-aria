# tests/hub/test_hub_entity_graph.py
"""Tests for EntityGraph integration with IntelligenceHub."""

import asyncio

import pytest

from aria.hub.core import IntelligenceHub
from aria.shared.entity_graph import EntityGraph


def test_hub_has_entity_graph(tmp_path):
    """Hub exposes an EntityGraph instance."""
    hub = IntelligenceHub(str(tmp_path / "hub.db"))
    assert hasattr(hub, "entity_graph")
    assert isinstance(hub.entity_graph, EntityGraph)


@pytest.mark.asyncio
async def test_entity_graph_refreshes_on_cache_update(tmp_path):
    """EntityGraph refreshes when entities/devices/areas cache is updated."""
    hub = IntelligenceHub(str(tmp_path / "hub.db"))
    await hub.initialize()

    try:
        # Store entity, device, and area data in cache
        await hub.set_cache(
            "entities", {"light.bedroom": {"entity_id": "light.bedroom", "device_id": "dev1", "area_id": None}}
        )
        await hub.set_cache("devices", {"dev1": {"device_id": "dev1", "area_id": "bedroom", "name": "Bedroom Lamp"}})
        await hub.set_cache("areas", [{"area_id": "bedroom", "name": "Bedroom"}])

        # Allow async subscriber callbacks to run
        await asyncio.sleep(0.05)

        # EntityGraph should have been refreshed
        assert hub.entity_graph.get_area("light.bedroom") == "bedroom"
    finally:
        await hub.shutdown()
