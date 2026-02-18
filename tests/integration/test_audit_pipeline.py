"""Integration tests — full audit pipeline: event → DB → query → verify."""

import asyncio

import pytest

from aria.hub.audit import AuditLogger
from aria.hub.core import IntelligenceHub, Module


@pytest.fixture
async def full_hub(tmp_path):
    cache_path = str(tmp_path / "hub.db")
    audit_path = str(tmp_path / "audit.db")
    hub = IntelligenceHub(cache_path)
    await hub.initialize()
    audit = AuditLogger()
    await audit.initialize(audit_path)
    hub.set_audit_logger(audit)
    yield hub, audit
    await hub.shutdown()
    await audit.shutdown()


class TestFullAuditChain:
    async def test_cache_write_creates_audit_event(self, full_hub):
        hub, audit = full_hub
        await hub.set_cache("test", {"data": 1})
        await audit.flush()
        events = await audit.query_events(event_type="cache.write")
        assert len(events) >= 1

    async def test_module_register_creates_audit_event(self, full_hub):
        hub, audit = full_hub
        mod = Module("integration_test", hub)
        hub.register_module(mod)
        await asyncio.sleep(0.1)  # let create_task run
        await audit.flush()
        events = await audit.query_events(event_type="module.register")
        assert len(events) >= 1

    async def test_integrity_check_after_writes(self, full_hub):
        hub, audit = full_hub
        for i in range(5):
            await hub.set_cache(f"cat_{i}", {"val": i})
        await audit.flush()
        result = await audit.verify_integrity()
        assert result["total"] >= 5
        assert result["invalid"] == 0

    async def test_request_id_correlation(self, full_hub):
        hub, audit = full_hub
        await audit.log_request("req-999", "GET", "/api/test", 200, 5.0, "127.0.0.1")
        await hub.emit_audit(
            event_type="test.correlated",
            source="hub",
            action="test",
            request_id="req-999",
        )
        await audit.flush()
        events = await audit.query_events(request_id="req-999")
        assert len(events) == 1
        reqs = await audit.query_requests()
        assert any(r["request_id"] == "req-999" for r in reqs)
