"""Tests for calendar context fetch — Google Calendar (gog) and HA calendar sources."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria.shared.calendar_context import fetch_calendar_events


class TestGoogleCalendarFetch:
    @pytest.mark.asyncio
    async def test_fetch_google_events(self):
        """gog CLI returns JSON list of events."""
        mock_output = json.dumps(
            [
                {"summary": "Team Standup", "start": "2026-02-20T09:00:00", "end": "2026-02-20T09:30:00"},
                {"summary": "Dentist", "start": "2026-02-20T14:00:00", "end": "2026-02-20T15:00:00"},
            ]
        )
        with patch("aria.shared.calendar_context._run_gog_cli", new_callable=AsyncMock) as mock_gog:
            mock_gog.return_value = mock_output
            events = await fetch_calendar_events(
                source="google",
                start_date="2026-02-20",
                end_date="2026-02-21",
            )
        assert len(events) == 2
        assert events[0]["summary"] == "Team Standup"
        assert events[1]["summary"] == "Dentist"

    @pytest.mark.asyncio
    async def test_google_empty_calendar(self):
        """Empty calendar returns empty list."""
        with patch("aria.shared.calendar_context._run_gog_cli", new_callable=AsyncMock) as mock_gog:
            mock_gog.return_value = "[]"
            events = await fetch_calendar_events(
                source="google",
                start_date="2026-02-20",
                end_date="2026-02-21",
            )
        assert events == []

    @pytest.mark.asyncio
    async def test_google_cli_failure_returns_empty(self):
        """gog CLI failure degrades gracefully to empty list."""
        with patch("aria.shared.calendar_context._run_gog_cli", new_callable=AsyncMock) as mock_gog:
            mock_gog.side_effect = Exception("gog not found")
            events = await fetch_calendar_events(
                source="google",
                start_date="2026-02-20",
                end_date="2026-02-21",
            )
        assert events == []

    @pytest.mark.asyncio
    async def test_google_invalid_json_returns_empty(self):
        """Malformed gog output degrades gracefully."""
        with patch("aria.shared.calendar_context._run_gog_cli", new_callable=AsyncMock) as mock_gog:
            mock_gog.return_value = "not valid json"
            events = await fetch_calendar_events(
                source="google",
                start_date="2026-02-20",
                end_date="2026-02-21",
            )
        assert events == []

    @pytest.mark.asyncio
    async def test_google_multi_day_event(self):
        """Multi-day events (vacations) are returned correctly."""
        mock_output = json.dumps(
            [
                {"summary": "Vacation", "start": "2026-03-01", "end": "2026-03-05"},
            ]
        )
        with patch("aria.shared.calendar_context._run_gog_cli", new_callable=AsyncMock) as mock_gog:
            mock_gog.return_value = mock_output
            events = await fetch_calendar_events(
                source="google",
                start_date="2026-03-01",
                end_date="2026-03-06",
            )
        assert len(events) == 1
        assert events[0]["summary"] == "Vacation"


class TestHACalendarFetch:
    @pytest.mark.asyncio
    async def test_fetch_ha_events(self):
        """HA calendar entity returns events from API."""
        mock_response = [
            {
                "summary": "Holiday",
                "start": {"dateTime": "2026-12-25T00:00:00"},
                "end": {"dateTime": "2026-12-26T00:00:00"},
            },
        ]
        with patch("aria.shared.calendar_context._fetch_ha_calendar", new_callable=AsyncMock) as mock_ha:
            mock_ha.return_value = mock_response
            events = await fetch_calendar_events(
                source="ha",
                start_date="2026-12-25",
                end_date="2026-12-26",
                entity_id="calendar.holidays",
            )
        assert len(events) == 1
        assert events[0]["summary"] == "Holiday"

    @pytest.mark.asyncio
    async def test_ha_no_entity_id_returns_empty(self):
        """HA source without entity_id returns empty list."""
        events = await fetch_calendar_events(
            source="ha",
            start_date="2026-02-20",
            end_date="2026-02-21",
            entity_id=None,
        )
        assert events == []

    @pytest.mark.asyncio
    async def test_ha_api_failure_returns_empty(self):
        """HA API failure degrades gracefully."""
        with patch("aria.shared.calendar_context._fetch_ha_calendar", new_callable=AsyncMock) as mock_ha:
            mock_ha.side_effect = Exception("HA unreachable")
            events = await fetch_calendar_events(
                source="ha",
                start_date="2026-02-20",
                end_date="2026-02-21",
                entity_id="calendar.holidays",
            )
        assert events == []


class TestGogTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kills_subprocess(self):
        """gog CLI timeout must call proc.kill() and raise RuntimeError."""

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch(
                "aria.shared.calendar_context.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
            pytest.raises(RuntimeError, match="gog CLI timed out"),
        ):
            from aria.shared.calendar_context import _run_gog_cli

            await _run_gog_cli("2026-02-20", "2026-02-21")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


class TestDisabledCalendar:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        """Disabled calendar returns empty without calling any source."""
        events = await fetch_calendar_events(
            source="disabled",
            start_date="2026-02-20",
            end_date="2026-02-21",
        )
        assert events == []

    @pytest.mark.asyncio
    async def test_unknown_source_returns_empty(self):
        """Unknown source type degrades gracefully."""
        events = await fetch_calendar_events(
            source="outlook",
            start_date="2026-02-20",
            end_date="2026-02-21",
        )
        assert events == []
