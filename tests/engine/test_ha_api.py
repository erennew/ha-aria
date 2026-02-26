"""Tests for ha_api.py — calendar event parsing (#203)."""

from unittest.mock import MagicMock, patch

# =============================================================================
# #203 — calendar event elif >= 5 branch must be reachable
# =============================================================================


def test_calendar_event_five_columns_uses_correct_offsets():
    """#203: 5-column calendar lines must parse from offsets [2,3,4], not [1,2,3].

    The bug: `if len(parts) >= 4` catches 5-column rows first, reading from
    wrong offsets. Fix: check >= 5 BEFORE >= 4.
    """
    from aria.engine.collectors.ha_api import fetch_calendar_events

    # Simulate gog output: header line + 5-column event line
    # Format: id\tcalendar\tstart\tend\tsummary
    five_col_output = "id\tcalendar\tstart\tend\tsummary\ncal1\twork\t09:00\t10:00\tTeam Standup"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = five_col_output

    with patch("aria.engine.collectors.ha_api.subprocess.run", return_value=mock_result):
        events = fetch_calendar_events()

    assert len(events) == 1
    # With the fix (>= 5 checked first), offsets [2,3,4] → start=09:00, end=10:00, summary=Team Standup
    assert events[0]["summary"] == "Team Standup", (
        f"5-column row parsed wrong summary: got '{events[0]['summary']}'. "
        "Likely the >= 4 branch fired before >= 5 branch."
    )
    assert events[0]["start"] == "09:00", f"Wrong start: {events[0]['start']}"
    assert events[0]["end"] == "10:00", f"Wrong end: {events[0]['end']}"


def test_calendar_event_four_columns_still_works():
    """#203: 4-column calendar lines must still parse correctly after fix.

    The 4-column format is: col0\tstart\tend\tsummary
    The >= 4 branch reads start=parts[1], end=parts[2], summary=parts[3].
    """
    from aria.engine.collectors.ha_api import fetch_calendar_events

    # Format: col0\tstart\tend\tsummary (4 cols, start at index 1)
    four_col_output = "header\ncal1\t09:00\t10:00\tDaily Sync"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = four_col_output

    with patch("aria.engine.collectors.ha_api.subprocess.run", return_value=mock_result):
        events = fetch_calendar_events()

    assert len(events) == 1
    assert events[0]["start"] == "09:00"
    assert events[0]["end"] == "10:00"
    assert events[0]["summary"] == "Daily Sync"
