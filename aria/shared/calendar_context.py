"""Calendar context fetch — Google Calendar (gog CLI) and HA calendar entity.

Fetches calendar events for day-type classification. Supports two sources:
- Google Calendar via the `gog` CLI tool
- Home Assistant calendar entity via REST API

Degrades gracefully: any failure returns an empty list, never breaks the pipeline.
"""

import asyncio
import json
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)


async def fetch_calendar_events(
    source: str,
    start_date: str,
    end_date: str,
    entity_id: str | None = None,
) -> list[dict]:
    """Fetch calendar events from configured source.

    Args:
        source: "google", "ha", or "disabled".
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        entity_id: HA calendar entity ID (required for source="ha").

    Returns:
        List of dicts with keys: summary, start, end.
        Empty list on any failure (graceful degradation).
    """
    if source == "google":
        return await _fetch_google_events(start_date, end_date)
    if source == "ha":
        return await _fetch_ha_events(start_date, end_date, entity_id)
    return []


async def _fetch_google_events(start_date: str, end_date: str) -> list[dict]:
    """Fetch events from Google Calendar via gog CLI."""
    try:
        raw = await _run_gog_cli(start_date, end_date)
        events = json.loads(raw)
        return [{"summary": e.get("summary", ""), "start": e.get("start", ""), "end": e.get("end", "")} for e in events]
    except Exception:
        logger.warning("Google Calendar fetch failed, returning empty list")
        return []


async def _fetch_ha_events(start_date: str, end_date: str, entity_id: str | None) -> list[dict]:
    """Fetch events from HA calendar entity via REST API."""
    if not entity_id:
        return []
    try:
        raw_events = await _fetch_ha_calendar(start_date, end_date, entity_id)
        return [_normalize_ha_event(e) for e in raw_events]
    except Exception:
        logger.warning("HA calendar fetch failed for %s, returning empty list", entity_id)
        return []


def _normalize_ha_event(event: dict) -> dict:
    """Normalize HA calendar event to standard format."""
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "summary": event.get("summary", ""),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
    }


async def _run_gog_cli(start_date: str, end_date: str) -> str:
    """Run gog calendar list and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "gog",
        "calendar",
        "list",
        "--from",
        start_date,
        "--to",
        end_date,
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"gog CLI failed: {stderr.decode()}")
    return stdout.decode()


async def _fetch_ha_calendar(start_date: str, end_date: str, entity_id: str) -> list[dict]:
    """Fetch events from HA REST API."""
    ha_url = os.environ.get("HA_URL", "")
    ha_token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        raise RuntimeError("HA_URL or HA_TOKEN not configured")

    url = f"{ha_url}/api/calendars/{entity_id}?start={start_date}&end={end_date}"
    headers = {"Authorization": f"Bearer {ha_token}"}
    async with (
        aiohttp.ClientSession() as session,
        session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp,
    ):
        resp.raise_for_status()
        return await resp.json()
