"""Test that get_module is synchronous and returns Module or None."""

from unittest.mock import MagicMock

from aria.hub.core import IntelligenceHub


class TestGetModule:
    def test_get_module_returns_registered_module(self):
        """get_module should return a module by ID synchronously."""
        hub = IntelligenceHub.__new__(IntelligenceHub)
        hub.modules = {}
        mock_module = MagicMock()
        mock_module.module_id = "test_mod"
        hub.modules["test_mod"] = mock_module

        result = hub.get_module("test_mod")
        assert result is mock_module

    def test_get_module_returns_none_for_missing(self):
        """get_module should return None for unregistered module."""
        hub = IntelligenceHub.__new__(IntelligenceHub)
        hub.modules = {}

        result = hub.get_module("nonexistent")
        assert result is None

    def test_get_module_is_not_coroutine(self):
        """get_module should NOT be a coroutine (it's just a dict lookup)."""
        import asyncio

        hub = IntelligenceHub.__new__(IntelligenceHub)
        hub.modules = {}

        result = hub.get_module("anything")
        assert not asyncio.iscoroutine(result)
