"""Known-answer tests for AuditLogger.

Validates that audit events are written to SQLite with correct fields,
checksums are valid SHA-256, and entry structure matches a golden snapshot.
"""

import re

import pytest

from aria.hub.audit import AuditLogger
from tests.integration.known_answer.conftest import golden_compare

# Deterministic test inputs
EVENT_TYPE = "entity_change"
SOURCE = "discovery"
ACTION = "status_update"
SUBJECT = "sensor.living_room_temp"
DETAIL = {"old_status": "active", "new_status": "stale"}
REQUEST_ID = "req-ka-001"
SEVERITY = "info"


@pytest.fixture
async def audit(tmp_path):
    """Create an AuditLogger backed by a temp SQLite database."""
    logger = AuditLogger(buffer_size=100)
    await logger.initialize(str(tmp_path / "audit.db"))
    yield logger
    await logger.shutdown()


@pytest.mark.asyncio
async def test_writes_audit_entry(audit):
    """Log an event, flush, query back, and verify all fields are present and correct."""
    await audit.log(
        event_type=EVENT_TYPE,
        source=SOURCE,
        action=ACTION,
        subject=SUBJECT,
        detail=DETAIL,
        request_id=REQUEST_ID,
        severity=SEVERITY,
    )
    await audit.flush()

    events = await audit.query_events(event_type=EVENT_TYPE)
    assert len(events) == 1, f"Expected 1 event, got {len(events)}"

    entry = events[0]

    # Verify all required fields exist
    expected_fields = {
        "id",
        "timestamp",
        "event_type",
        "source",
        "action",
        "subject",
        "detail",
        "request_id",
        "severity",
        "checksum",
    }
    assert set(entry.keys()) == expected_fields, (
        f"Field mismatch: missing={expected_fields - set(entry.keys())}, extra={set(entry.keys()) - expected_fields}"
    )

    # Verify values match what we logged
    assert entry["event_type"] == EVENT_TYPE
    assert entry["source"] == SOURCE
    assert entry["action"] == ACTION
    assert entry["subject"] == SUBJECT
    assert entry["detail"] == DETAIL
    assert entry["request_id"] == REQUEST_ID
    assert entry["severity"] == SEVERITY
    assert isinstance(entry["id"], int)
    assert entry["timestamp"]  # non-empty ISO timestamp


@pytest.mark.asyncio
async def test_checksum_integrity(audit):
    """Verify checksum is valid SHA-256 (64 hex chars) and passes integrity check."""
    await audit.log(
        event_type=EVENT_TYPE,
        source=SOURCE,
        action=ACTION,
        subject=SUBJECT,
        detail=DETAIL,
        severity=SEVERITY,
    )
    await audit.flush()

    events = await audit.query_events(event_type=EVENT_TYPE)
    assert len(events) == 1
    checksum = events[0]["checksum"]

    # SHA-256 produces exactly 64 lowercase hex characters
    assert re.fullmatch(r"[0-9a-f]{64}", checksum), f"Checksum is not valid SHA-256 hex: {checksum!r}"

    # verify_integrity recomputes checksums and confirms they match
    result = await audit.verify_integrity()
    assert result["total"] == 1
    assert result["valid"] == 1
    assert result["invalid"] == 0
    assert result["details"] == []


@pytest.mark.asyncio
async def test_golden_snapshot(audit, update_golden):
    """Golden snapshot of audit entry structure (timestamps and checksums stripped)."""
    await audit.log(
        event_type=EVENT_TYPE,
        source=SOURCE,
        action=ACTION,
        subject=SUBJECT,
        detail=DETAIL,
        request_id=REQUEST_ID,
        severity=SEVERITY,
    )
    await audit.flush()

    events = await audit.query_events(event_type=EVENT_TYPE)
    assert len(events) == 1

    entry = events[0]

    # Strip non-deterministic fields for golden comparison
    snapshot = {k: v for k, v in entry.items() if k not in ("id", "timestamp", "checksum")}

    golden_compare(snapshot, "audit_logger_entry", update=update_golden)
