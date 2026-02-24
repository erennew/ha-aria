"""Tests for IntelligenceHub.publish() — backpressure monitoring and dual dispatch.

Covers:
  - Issue #31: slow-subscriber warning when callback or on_event() exceeds 100 ms
  - Issue #32: both dispatch paths (subscribe callbacks + module.on_event()) fire
               on every publish()
"""

import asyncio
import logging
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from aria.hub.core import IntelligenceHub, Module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def hub():
    """Minimal initialized hub backed by a temp SQLite file."""
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "test_hub.db"
        h = IntelligenceHub(str(cache_path))
        await h.initialize()
        yield h
        await h.shutdown()


# ---------------------------------------------------------------------------
# Helper: concrete Module subclass whose on_event() we can track
# ---------------------------------------------------------------------------


class TrackingModule(Module):
    """Module that records every on_event() call."""

    def __init__(self, module_id: str, hub: IntelligenceHub):
        super().__init__(module_id, hub)
        self.received: list[tuple[str, dict]] = []

    async def on_event(self, event_type: str, data: dict) -> None:
        self.received.append((event_type, data))


# ---------------------------------------------------------------------------
# Issue #31 — backpressure monitoring
# ---------------------------------------------------------------------------


class TestBackpressureMonitoring:
    """publish() emits a warning when a subscriber callback is slow (> 100 ms)."""

    @pytest.mark.asyncio
    async def test_slow_subscribe_callback_triggers_warning(self, hub, caplog):
        """A callback that sleeps > 100 ms must produce a logger.warning."""

        async def slow_callback(data: dict) -> None:
            await asyncio.sleep(0.15)  # 150 ms — over the 100 ms threshold

        hub.subscribe("test_slow", slow_callback)

        with caplog.at_level(logging.WARNING, logger="hub"):
            await hub.publish("test_slow", {"key": "value"})

        slow_warnings = [r for r in caplog.records if "Slow" in r.message and r.levelno == logging.WARNING]
        assert slow_warnings, (
            "Expected at least one WARNING about a slow subscriber callback, got none.\n"
            f"Captured log records: {[r.message for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_fast_callback_does_not_warn(self, hub, caplog):
        """A callback that completes well under 100 ms must not produce a warning."""

        async def fast_callback(data: dict) -> None:
            pass  # negligible

        hub.subscribe("test_fast", fast_callback)

        with caplog.at_level(logging.WARNING, logger="hub"):
            await hub.publish("test_fast", {"key": "value"})

        slow_warnings = [r for r in caplog.records if "Slow" in r.message and r.levelno == logging.WARNING]
        assert not slow_warnings, (
            f"Unexpected slow-subscriber warning for a fast callback: {[r.message for r in slow_warnings]}"
        )

    @pytest.mark.asyncio
    async def test_slow_on_event_triggers_warning(self, hub, caplog):
        """A module whose on_event() sleeps > 100 ms must trigger the warning."""

        class SlowModule(Module):
            async def on_event(self, event_type: str, data: dict) -> None:
                await asyncio.sleep(0.15)

        slow_mod = SlowModule("slow_module", hub)
        hub.register_module(slow_mod)

        with caplog.at_level(logging.WARNING, logger="hub"):
            await hub.publish("any_event", {})

        slow_warnings = [r for r in caplog.records if "Slow" in r.message and r.levelno == logging.WARNING]
        assert slow_warnings, (
            "Expected a WARNING for slow on_event(), got none.\n"
            f"Captured records: {[r.message for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_event_count_increments(self, hub):
        """_event_count must increment by 1 for each publish() call."""
        initial = hub._event_count
        await hub.publish("count_test", {})
        await hub.publish("count_test", {})
        assert hub._event_count == initial + 2


# ---------------------------------------------------------------------------
# Issue #32 — dual dispatch
# ---------------------------------------------------------------------------


class TestDualDispatch:
    """Both dispatch paths fire on every publish()."""

    @pytest.mark.asyncio
    async def test_subscribe_callback_fires(self, hub):
        """Explicit subscribe() callback is invoked when the matching event is published."""
        received: list[dict] = []

        async def callback(data: dict) -> None:
            received.append(data)

        hub.subscribe("dual_test", callback)
        await hub.publish("dual_test", {"marker": "subscribe_path"})

        assert len(received) == 1
        assert received[0]["marker"] == "subscribe_path"

    @pytest.mark.asyncio
    async def test_module_on_event_fires(self, hub):
        """module.on_event() is invoked on every publish() regardless of event type."""
        mod = TrackingModule("tracker", hub)
        hub.register_module(mod)

        await hub.publish("dual_test", {"marker": "on_event_path"})

        assert any(et == "dual_test" for et, _ in mod.received), (
            f"Expected 'dual_test' in module received events, got: {mod.received}"
        )

    @pytest.mark.asyncio
    async def test_both_paths_fire_on_same_publish(self, hub):
        """A single publish() fires BOTH the subscribe callback AND module.on_event()."""
        subscribe_calls: list[dict] = []
        on_event_calls: list[tuple[str, dict]] = []

        async def sub_callback(data: dict) -> None:
            subscribe_calls.append(data)

        class DualWatcher(Module):
            async def on_event(self, event_type: str, data: dict) -> None:
                on_event_calls.append((event_type, data))

        watcher = DualWatcher("dual_watcher", hub)
        hub.register_module(watcher)
        hub.subscribe("dual_both", sub_callback)

        await hub.publish("dual_both", {"payload": 42})

        assert len(subscribe_calls) == 1, f"subscribe() callback should fire once, fired {len(subscribe_calls)} time(s)"
        assert any(et == "dual_both" for et, _ in on_event_calls), (
            f"module.on_event() should receive 'dual_both', got: {on_event_calls}"
        )

    @pytest.mark.asyncio
    async def test_unrelated_event_still_reaches_module(self, hub):
        """Modules receive ALL events via on_event(), not just subscribed ones."""
        mod = TrackingModule("observer", hub)
        hub.register_module(mod)

        # No subscribe() call — module receives event only via on_event() broadcast
        await hub.publish("unsubscribed_event", {"x": 1})

        assert any(et == "unsubscribed_event" for et, _ in mod.received), (
            "Module should receive events via on_event() even without an explicit subscribe()"
        )

    @pytest.mark.asyncio
    async def test_subscribe_only_fires_for_matching_event_type(self, hub):
        """subscribe() callback is NOT called for non-matching event types."""
        wrong_calls: list[dict] = []

        async def callback(data: dict) -> None:
            wrong_calls.append(data)

        hub.subscribe("specific_event", callback)
        await hub.publish("other_event", {"y": 2})

        assert not wrong_calls, "subscribe() callback fired for a non-matching event type — should not happen"


# ---------------------------------------------------------------------------
# C4 — Subscriber snapshot concurrent modification safety
# ---------------------------------------------------------------------------


class TestSubscriberSnapshotSafety:
    """publish() must snapshot subscribers before iterating to avoid RuntimeError."""

    @pytest.mark.asyncio
    async def test_publish_snapshot_safety(self, hub):
        """Unsubscribing inside a callback must not raise RuntimeError."""
        call_count = 0

        async def self_removing_callback(data: dict) -> None:
            nonlocal call_count
            call_count += 1
            # Unsubscribe during iteration — would raise RuntimeError without snapshot
            hub.unsubscribe("snapshot_test", self_removing_callback)

        hub.subscribe("snapshot_test", self_removing_callback)

        # Should not raise RuntimeError: Set changed size during iteration
        await hub.publish("snapshot_test", {"marker": "snapshot"})
        assert call_count == 1

        # Second publish should not call the unsubscribed callback
        await hub.publish("snapshot_test", {"marker": "snapshot2"})
        assert call_count == 1


# ---------------------------------------------------------------------------
# C8 — create_task done callback logs exceptions
# ---------------------------------------------------------------------------


class TestCreateTaskDoneCallback:
    """Background task exceptions must be logged via done_callback (lesson #43)."""

    @pytest.mark.asyncio
    async def test_create_task_logs_exception_via_callback(self, hub, caplog):
        """A failing background task must produce an error log via done_callback."""

        async def failing_coro():
            raise ValueError("test task failure")

        task = asyncio.get_event_loop().create_task(failing_coro())
        task.add_done_callback(hub._log_task_exception)

        # Wait for task to complete (and fail)
        with pytest.raises(ValueError):
            await task

        # Allow event loop to process callbacks
        await asyncio.sleep(0)

        # Verify error was logged — the message contains the task name,
        # the exception details are in exc_info (shown in full log text)
        error_records = [
            r for r in caplog.records if r.levelno >= logging.ERROR and "Unhandled exception in task" in r.message
        ]
        assert error_records, f"Expected error log about task exception, got: {[r.message for r in caplog.records]}"
        # Verify exc_info was passed (full traceback available)
        assert error_records[0].exc_info is not None, "exc_info should be set for full traceback"
