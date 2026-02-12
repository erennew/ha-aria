"""Activity Monitor Module - Adaptive snapshots and activity event logging.

Connects to HA WebSocket, tracks state_changed events, triggers extra
intraday snapshots when the home is occupied and active, and maintains
a rolling 24-hour activity log in 15-minute windows.
"""

import asyncio
import json
import logging
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from hub.core import Module, IntelligenceHub


logger = logging.getLogger(__name__)


# Domains worth tracking for activity detection
TRACKED_DOMAINS = {
    "light", "switch", "binary_sensor", "lock", "media_player",
    "cover", "climate", "vacuum", "person", "device_tracker", "fan",
}

# sensor is only tracked when device_class == "power"
CONDITIONAL_DOMAINS = {"sensor"}

# Transitions that are pure noise
NOISE_TRANSITIONS = {
    ("unavailable", "unknown"),
    ("unknown", "unavailable"),
}

# Max snapshots per day and cooldown between triggered snapshots
DAILY_SNAPSHOT_CAP = 20
SNAPSHOT_COOLDOWN_S = 1800  # 30 minutes

# How often to flush buffered events into cache windows
FLUSH_INTERVAL_S = 900  # 15 minutes

# Rolling window retention
MAX_WINDOW_AGE_H = 24


class ActivityMonitor(Module):
    """Tracks HA state changes and triggers adaptive snapshots."""

    def __init__(self, hub: IntelligenceHub, ha_url: str, ha_token: str):
        super().__init__("activity_monitor", hub)
        self.ha_url = ha_url
        self.ha_token = ha_token

        # In-memory event buffer (flushed every 15 min)
        self._activity_buffer: List[Dict[str, Any]] = []
        # Ring buffer of recent events — survives flushes, for dashboard display
        self._recent_events: deque = deque(maxlen=20)

        # Occupancy state
        self._occupancy_state = False
        self._occupancy_people: List[str] = []
        self._occupancy_since: Optional[str] = None

        # Snapshot control
        self._last_snapshot_time: Optional[datetime] = None
        self._snapshots_today = 0
        self._snapshot_date = datetime.now().strftime("%Y-%m-%d")

        # Stats
        self._events_today = 0
        self._events_date = datetime.now().strftime("%Y-%m-%d")

        # Path to ha-intelligence CLI
        self._ha_intelligence = Path.home() / ".local" / "bin" / "ha-intelligence"

        # Persistent snapshot log (append-only JSONL, never pruned)
        self._snapshot_log_path = (
            Path.home() / "ha-logs" / "intelligence" / "snapshot_log.jsonl"
        )
        self._snapshot_log_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """Start the WebSocket listener and buffer flush timer."""
        self.logger.info("Activity monitor initializing...")

        # Start WebSocket listener
        await self.hub.schedule_task(
            task_id="activity_ws_listener",
            coro=self._ws_listen_loop,
            interval=None,
            run_immediately=True,
        )

        # Start periodic buffer flush
        await self.hub.schedule_task(
            task_id="activity_buffer_flush",
            coro=self._flush_activity_buffer,
            interval=timedelta(seconds=FLUSH_INTERVAL_S),
            run_immediately=False,
        )

        self.logger.info("Activity monitor started")

    async def on_event(self, event_type: str, data: Dict[str, Any]):
        pass

    # ------------------------------------------------------------------
    # WebSocket listener (follows discovery.py pattern)
    # ------------------------------------------------------------------

    async def _ws_listen_loop(self):
        """Connect to HA WebSocket and listen for state_changed events."""
        ws_url = self.ha_url.replace("http", "ws", 1) + "/api/websocket"
        retry_delay = 5

        while self.hub.is_running():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url) as ws:
                        # 1. Wait for auth_required
                        msg = await ws.receive_json()
                        if msg.get("type") != "auth_required":
                            self.logger.error(f"Unexpected WS message: {msg}")
                            continue

                        # 2. Authenticate
                        await ws.send_json({
                            "type": "auth",
                            "access_token": self.ha_token,
                        })
                        auth_resp = await ws.receive_json()
                        if auth_resp.get("type") != "auth_ok":
                            self.logger.error(f"WS auth failed: {auth_resp}")
                            await asyncio.sleep(retry_delay)
                            continue

                        self.logger.info(
                            "Activity WebSocket connected — listening for state_changed"
                        )
                        retry_delay = 5  # reset backoff

                        # 3. Subscribe to state_changed
                        await ws.send_json({
                            "id": 1,
                            "type": "subscribe_events",
                            "event_type": "state_changed",
                        })

                        # 4. Listen loop
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if data.get("type") == "event":
                                    event_data = data.get("event", {}).get("data", {})
                                    self._handle_state_changed(event_data)
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.logger.warning(
                    f"Activity WebSocket error: {e} — retrying in {retry_delay}s"
                )
            except Exception as e:
                self.logger.error(f"Activity WebSocket unexpected error: {e}")

            # Backoff: 5s → 10s → 20s → 60s max
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle_state_changed(self, data: Dict[str, Any]):
        """Filter and buffer a single state_changed event."""
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state") or {}
        old_state = data.get("old_state") or {}

        domain = entity_id.split(".")[0] if "." in entity_id else ""

        # Domain filter
        if domain not in TRACKED_DOMAINS and domain not in CONDITIONAL_DOMAINS:
            return

        # Conditional: sensor only if device_class == power
        if domain in CONDITIONAL_DOMAINS:
            device_class = new_state.get("attributes", {}).get("device_class", "")
            if device_class != "power":
                return

        from_state = old_state.get("state", "")
        to_state = new_state.get("state", "")

        # Filter noise transitions
        if (from_state, to_state) in NOISE_TRANSITIONS:
            return
        if from_state == to_state:
            return

        # Reset daily counters at midnight
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._events_date:
            self._events_today = 0
            self._events_date = today
        if today != self._snapshot_date:
            self._snapshots_today = 0
            self._snapshot_date = today

        self._events_today += 1

        # Build event record
        now = datetime.now()
        attrs = new_state.get("attributes", {})
        friendly_name = attrs.get("friendly_name", entity_id)
        device_class = attrs.get("device_class", "")
        event = {
            "entity_id": entity_id,
            "domain": domain,
            "device_class": device_class,
            "from": from_state,
            "to": to_state,
            "time": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(),
            "friendly_name": friendly_name,
        }
        self._activity_buffer.append(event)
        self._recent_events.append(event)

        # Update occupancy
        if domain in ("person", "device_tracker"):
            self._update_occupancy(entity_id, to_state, friendly_name)

        # Maybe trigger snapshot
        self._maybe_trigger_snapshot()

    def _update_occupancy(self, entity_id: str, state: str, friendly_name: str):
        """Track occupancy from person/device_tracker entities."""
        # person entities: state == "home" means home
        domain = entity_id.split(".")[0]
        if domain == "person":
            name = friendly_name or entity_id.split(".")[-1].replace("_", " ").title()

            if state == "home":
                if name not in self._occupancy_people:
                    self._occupancy_people.append(name)
                if not self._occupancy_state:
                    self._occupancy_state = True
                    self._occupancy_since = datetime.now().isoformat()
                    self.logger.info(f"Occupancy: home ({name})")
            else:
                if name in self._occupancy_people:
                    self._occupancy_people.remove(name)
                if not self._occupancy_people:
                    self._occupancy_state = False
                    self.logger.info("Occupancy: away (all people left)")

    def _maybe_trigger_snapshot(self):
        """Trigger an extra intraday snapshot if conditions are met."""
        if not self._occupancy_state:
            return

        if self._snapshots_today >= DAILY_SNAPSHOT_CAP:
            return

        now = datetime.now()
        if self._last_snapshot_time:
            elapsed = (now - self._last_snapshot_time).total_seconds()
            if elapsed < SNAPSHOT_COOLDOWN_S:
                return

        # Need meaningful activity — at least 5 events in the buffer
        if len(self._activity_buffer) < 5:
            return

        self._last_snapshot_time = now
        self._snapshots_today += 1

        # Count events by domain in current buffer for context
        domain_counts = defaultdict(int)
        for evt in self._activity_buffer:
            domain_counts[evt["domain"]] += 1

        log_entry = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "number": self._snapshots_today,
            "buffered_events": len(self._activity_buffer),
            "people": list(self._occupancy_people),
            "domains": dict(sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)),
        }
        self._append_snapshot_log(log_entry)

        self.logger.info(
            f"Triggering adaptive snapshot ({self._snapshots_today}/{DAILY_SNAPSHOT_CAP} today)"
        )

        # Fire-and-forget subprocess
        asyncio.get_event_loop().run_in_executor(None, self._run_snapshot)

    def _run_snapshot(self):
        """Run ha-intelligence --snapshot-intraday in a subprocess."""
        try:
            result = subprocess.run(
                [str(self._ha_intelligence), "--snapshot-intraday"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                self.logger.warning(
                    f"Snapshot subprocess failed: {result.stderr[:200]}"
                )
            else:
                self.logger.info("Adaptive snapshot completed")
        except FileNotFoundError:
            self.logger.warning(
                f"ha-intelligence not found at {self._ha_intelligence}"
            )
        except subprocess.TimeoutExpired:
            self.logger.warning("Snapshot subprocess timed out after 30s")
        except Exception as e:
            self.logger.error(f"Snapshot subprocess error: {e}")

    # ------------------------------------------------------------------
    # Persistent snapshot log (JSONL, append-only)
    # ------------------------------------------------------------------

    def _append_snapshot_log(self, entry: Dict[str, Any]):
        """Append a snapshot record to the persistent JSONL log."""
        try:
            with open(self._snapshot_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            self.logger.warning(f"Failed to write snapshot log: {e}")

    def _read_snapshot_log_today(self) -> List[Dict[str, Any]]:
        """Read today's entries from the persistent snapshot log."""
        today = datetime.now().strftime("%Y-%m-%d")
        entries = []
        if not self._snapshot_log_path.exists():
            return entries
        try:
            with open(self._snapshot_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("date") == today:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.logger.warning(f"Failed to read snapshot log: {e}")
        return entries

    # ------------------------------------------------------------------
    # Buffer flush — 15-minute windows → cache
    # ------------------------------------------------------------------

    async def _flush_activity_buffer(self):
        """Group buffered events into a 15-min window and write to cache."""
        if not self._activity_buffer:
            await self._update_summary_cache()
            return

        now = datetime.now()
        # Window boundaries
        minute_slot = (now.minute // 15) * 15
        window_start = now.replace(minute=minute_slot, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15) - timedelta(seconds=1)

        # Group events by domain
        by_domain: Dict[str, int] = defaultdict(int)
        notable: List[Dict[str, Any]] = []
        for evt in self._activity_buffer:
            by_domain[evt["domain"]] += 1
            # Notable = non-binary_sensor events, or lock/door events
            domain = evt["domain"]
            if domain in ("lock", "cover", "media_player", "climate", "vacuum"):
                notable.append({
                    "entity": evt["entity_id"],
                    "from": evt["from"],
                    "to": evt["to"],
                    "time": evt["time"][:5],  # HH:MM
                })

        window = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "event_count": len(self._activity_buffer),
            "by_domain": dict(by_domain),
            "notable_changes": notable[-10:],  # cap at 10
            "occupancy": self._occupancy_state,
        }

        # Read existing activity log from cache
        existing = await self.hub.get_cache("activity_log")
        windows = []
        if existing and existing.get("data"):
            windows = existing["data"].get("windows", [])

        # Prune windows older than 24 hours
        cutoff = (now - timedelta(hours=MAX_WINDOW_AGE_H)).isoformat()
        windows = [w for w in windows if w.get("window_start", "") >= cutoff]

        windows.append(window)

        activity_log = {
            "windows": windows,
            "last_updated": now.isoformat(),
            "events_today": self._events_today,
            "snapshots_today": self._snapshots_today,
        }

        await self.hub.set_cache("activity_log", activity_log, {
            "source": "activity_monitor",
            "window_count": len(windows),
        })

        self.logger.debug(
            f"Flushed {len(self._activity_buffer)} events into activity window"
        )

        # Clear buffer
        self._activity_buffer.clear()

        # Update summary cache
        await self._update_summary_cache()

    async def _update_summary_cache(self):
        """Write current activity summary for dashboard consumption."""
        now = datetime.now()

        # Recent activity: last 15 events from ring buffer (survives flushes)
        recent = []
        for evt in reversed(list(self._recent_events)):
            recent.append({
                "entity": evt["entity_id"],
                "domain": evt["domain"],
                "device_class": evt.get("device_class", ""),
                "from": evt["from"],
                "to": evt["to"],
                "time": evt["time"][:5],
                "friendly_name": evt.get("friendly_name", evt["entity_id"]),
            })
            if len(recent) >= 15:
                break

        # Activity rate from cached windows
        activity_log = await self.hub.get_cache("activity_log")
        windows = []
        if activity_log and activity_log.get("data"):
            windows = activity_log["data"].get("windows", [])

        current_count = len(self._activity_buffer)

        # Average events/window over last hour (up to 4 windows)
        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        recent_windows = [
            w for w in windows if w.get("window_start", "") >= one_hour_ago
        ]
        if recent_windows:
            avg_1h = sum(w["event_count"] for w in recent_windows) / len(recent_windows)
        else:
            avg_1h = 0

        trend = "stable"
        if current_count > avg_1h * 1.5 and avg_1h > 0:
            trend = "increasing"
        elif current_count < avg_1h * 0.5 and avg_1h > 0:
            trend = "decreasing"

        # Domain counts in last hour
        domains_1h: Dict[str, int] = defaultdict(int)
        for w in recent_windows:
            for domain, count in w.get("by_domain", {}).items():
                domains_1h[domain] += count
        # Also count current buffer
        for evt in self._activity_buffer:
            if evt.get("timestamp", "") >= one_hour_ago:
                domains_1h[evt["domain"]] += 1

        # Cooldown remaining
        cooldown_remaining = 0
        if self._last_snapshot_time:
            elapsed = (now - self._last_snapshot_time).total_seconds()
            cooldown_remaining = max(0, SNAPSHOT_COOLDOWN_S - elapsed)

        summary = {
            "occupancy": {
                "anyone_home": self._occupancy_state,
                "people": list(self._occupancy_people),
                "since": self._occupancy_since,
            },
            "recent_activity": recent,
            "activity_rate": {
                "current": current_count,
                "avg_1h": round(avg_1h, 1),
                "trend": trend,
            },
            "snapshot_status": {
                "last_triggered": self._last_snapshot_time.isoformat() if self._last_snapshot_time else None,
                "today_count": self._snapshots_today,
                "daily_cap": DAILY_SNAPSHOT_CAP,
                "cooldown_remaining_s": int(cooldown_remaining),
                "log_file": str(self._snapshot_log_path),
                "log_today": self._read_snapshot_log_today(),
            },
            "domains_active_1h": dict(
                sorted(domains_1h.items(), key=lambda x: x[1], reverse=True)
            ),
        }

        await self.hub.set_cache("activity_summary", summary, {
            "source": "activity_monitor",
        })
