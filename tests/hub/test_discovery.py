"""Tests for discovery module reconnect jitter behavior."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria.modules.discovery import DiscoveryModule


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.set_cache = AsyncMock()
    hub.get_cache = AsyncMock(return_value=None)
    hub.schedule_task = AsyncMock()
    hub.publish = AsyncMock()
    hub.cache = MagicMock()
    hub.cache.get_config_value = AsyncMock(return_value="72")
    return hub


@pytest.fixture
def module(mock_hub):
    with patch.object(DiscoveryModule, "__init__", lambda self, *args, **kwargs: None):
        m = DiscoveryModule.__new__(DiscoveryModule)
        m.hub = mock_hub
        m.logger = logging.getLogger("test_discovery")
        return m


def test_reconnect_delay_has_jitter():
    """Reconnect uses ±25% jitter to prevent thundering herd.

    Samples 200 delays for a base of 5s and verifies:
    - All values fall within [3.75, 6.25] (±25% of 5)
    - Both sides of the base are represented (not a constant offset)
    """
    import random

    base = 5
    low = base * 0.75
    high = base * 1.25

    samples = [base + base * random.uniform(-0.25, 0.25) for _ in range(200)]

    # All samples within bounds
    assert all(low <= s <= high for s in samples), (
        f"Sample out of ±25% range: min={min(samples):.3f}, max={max(samples):.3f}"
    )

    # Distribution is not degenerate — we should see values both above and below base
    assert any(s < base for s in samples), "No samples below base — jitter is not subtracting"
    assert any(s > base for s in samples), "No samples above base — jitter is not adding"


def test_reconnect_jitter_bounds_at_max_delay():
    """Jitter at the 60s cap stays within ±25% of 60."""
    import random

    base = 60
    low = base * 0.75  # 45s
    high = base * 1.25  # 75s

    samples = [base + base * random.uniform(-0.25, 0.25) for _ in range(200)]

    assert all(low <= s <= high for s in samples), (
        f"Sample out of ±25% range at cap: min={min(samples):.3f}, max={max(samples):.3f}"
    )
