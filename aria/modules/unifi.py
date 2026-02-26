"""UniFi Network + Protect presence signals for ARIA.

Two signal pipelines sharing one aiohttp session:
- Network: REST polling /proxy/network/api/s/{site}/stat/sta (WiFi clients)
- Protect: uiprotect WebSocket (smart detect events + face thumbnails)

Auth: X-API-Key header. ssl=False for Dream Machine self-signed cert.
"""

import asyncio
import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from aria.hub.core import Module

logger = logging.getLogger(__name__)


class UniFiModule(Module):
    """Supplementary presence signals from UniFi Network and Protect."""

    module_id = "unifi"

    def __init__(self, hub, host: str = "", api_key: str = ""):
        super().__init__("unifi", hub)
        # UNIFI_HOST env var overrides constructor arg (env is authoritative)
        self._host = os.environ.get("UNIFI_HOST", host).rstrip("/")
        self._api_key = os.environ.get("UNIFI_API_KEY", api_key)
        self._enabled: bool = False

        # Loaded from config in initialize()
        self._site: str = "default"
        self._poll_interval: int = 30
        self._ap_rooms: dict[str, str] = {}
        self._device_people: dict[str, str] = {}
        self._rssi_threshold: int = -75
        self._active_kbps: int = 100

        # Runtime state
        self._session = None  # aiohttp.ClientSession
        self._protect_client = None  # uiprotect.ProtectApiClient
        self._home_away: bool = True  # True = someone home, False = all away
        self._last_client_state: dict[str, Any] = {}  # MAC → client data (last poll)
        self._last_error: str | None = None

        # Subscriber callback references (for unsubscribe in shutdown)
        # UniFiModule currently uses no hub.subscribe() — signals are polled/pushed directly.

    def _load_config(self) -> None:
        """Load all unifi.* config values from hub."""
        enabled_str = self.hub.get_config_value("unifi.enabled", "false")
        self._enabled = str(enabled_str).lower() in ("true", "1", "yes")
        self._site = self.hub.get_config_value("unifi.site", "default")
        self._poll_interval = int(self.hub.get_config_value("unifi.poll_interval_s", 30))
        self._rssi_threshold = int(self.hub.get_config_value("unifi.rssi_room_threshold", -75))
        self._active_kbps = int(self.hub.get_config_value("unifi.device_active_kbps", 100))

        ap_rooms_raw = self.hub.get_config_value("unifi.ap_rooms", "{}")
        try:
            self._ap_rooms = json.loads(ap_rooms_raw) if ap_rooms_raw else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("unifi.ap_rooms is not valid JSON — using empty mapping")
            self._ap_rooms = {}

        device_people_raw = self.hub.get_config_value("unifi.device_people", "{}")
        try:
            self._device_people = json.loads(device_people_raw) if device_people_raw else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("unifi.device_people is not valid JSON — using empty mapping")
            self._device_people = {}

    async def initialize(self) -> None:
        """Load config and start polling/WebSocket loops if enabled."""
        self._load_config()

        if not self._enabled:
            logger.info("UniFi integration disabled (unifi.enabled=false)")
            return

        if not self._host:
            logger.warning("UniFi: no host configured (set UNIFI_HOST env var) — module disabled")
            self._enabled = False
            return

        if not self._api_key:
            logger.warning("UniFi: no API key configured (set UNIFI_API_KEY env var) — module disabled")
            self._enabled = False
            return

        import aiohttp

        self._session = aiohttp.ClientSession(
            headers={"X-API-Key": self._api_key},
            connector=aiohttp.TCPConnector(ssl=False),
        )
        logger.info("UniFi module initialized (host=%s, site=%s)", self._host, self._site)

        # Start loops — tracked as tasks by hub via log_task_exception pattern
        asyncio.create_task(self._network_poll_loop(), name="unifi_network_poll")
        asyncio.create_task(self._protect_ws_loop(), name="unifi_protect_ws")

    async def shutdown(self) -> None:
        """Close aiohttp session and disconnect Protect client."""
        if self._session:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None
        if self._protect_client:
            try:
                await self._protect_client.disconnect()
            except Exception as e:
                logger.debug("UniFi Protect: disconnect error during shutdown — %s", e)
            self._protect_client = None
        logger.info("UniFi module shut down")

    # ── Person and room resolution ────────────────────────────────────

    def _resolve_person(self, mac: str, hostname: str) -> str | None:
        """Resolve MAC → person name. device_people override > hostname > None."""
        if mac in self._device_people:
            return self._device_people[mac]
        return hostname if hostname else None

    def _resolve_room(self, ap_mac: str) -> str | None:
        """Resolve AP MAC → room name via ap_rooms config."""
        return self._ap_rooms.get(ap_mac)

    def _is_device_active(self, tx_bytes_r: int, rx_bytes_r: int) -> bool:
        """True if tx+rx rate exceeds device_active_kbps threshold."""
        kbps = (tx_bytes_r + rx_bytes_r) * 8 / 1000
        return kbps >= self._active_kbps

    def _compute_network_weight(self, rssi: int) -> float:
        """Base weight for network_client_present, halved if RSSI is ambiguous."""
        base = 0.75
        if rssi < self._rssi_threshold:
            return base * 0.5
        return base

    # ── Client state processing ───────────────────────────────────────

    def _process_clients(self, clients: list[dict]) -> list[dict]:
        """Process raw UniFi client list → signal dicts + update home/away state.

        Returns list of dicts: {room, signal_type, value, detail, ts}
        """
        ts = datetime.now(UTC)
        signals: list[dict] = []
        known_macs = set(self._device_people.keys())
        seen_known: set[str] = set()

        # Update cached client state (MAC → data) for cross-validation
        self._last_client_state = {c["mac"]: c for c in clients}

        for client in clients:
            mac = client.get("mac", "")
            ap_mac = client.get("ap_mac", "")
            hostname = client.get("hostname", "")
            rssi = client.get("rssi", -90)
            tx_bytes_r = client.get("tx_bytes_r", 0)
            rx_bytes_r = client.get("rx_bytes_r", 0)

            person = self._resolve_person(mac, hostname)
            room = self._resolve_room(ap_mac)

            # Track known devices for home/away gate
            if mac in known_macs:
                seen_known.add(mac)

            if room is None:
                continue  # Can't place in room — skip room signals; home/away still tracked

            weight = self._compute_network_weight(rssi)
            detail = f"{person or hostname}@{room} rssi={rssi}"
            signals.append(
                {
                    "room": room,
                    "signal_type": "network_client_present",
                    "value": weight,
                    "detail": detail,
                    "ts": ts,
                }
            )

            if self._is_device_active(tx_bytes_r, rx_bytes_r):
                signals.append(
                    {
                        "room": room,
                        "signal_type": "device_active",
                        "value": 0.85,  # High confidence — active tx/rx proves device (and person) is present
                        "detail": f"{person or hostname} active",
                        "ts": ts,
                    }
                )

        # Update home/away gate
        self._home_away = len(seen_known) > 0 if known_macs else True
        return signals

    # ── Stub loops (implemented in Tasks 5, 6) ────────────────────────

    async def _network_poll_loop(self) -> None:
        """Poll UniFi Network for WiFi client state every poll_interval_s."""
        url = f"https://{self._host}/proxy/network/api/s/{self._site}/stat/sta"
        while self.hub.is_running():
            if not self._enabled:
                break
            try:
                async with self._session.get(url) as resp:
                    if resp.status == 401:
                        self._last_error = "API key invalid (401)"
                        logger.error("UniFi Network: API key invalid — disabling module")
                        self._enabled = False
                        return
                    resp.raise_for_status()
                    data = await resp.json()
                    clients = data.get("data", [])
                    signals = self._process_clients(clients)

                    # Publish signals to hub for PresenceModule cross-validation
                    await self.hub.set_cache(
                        "unifi_client_state",
                        {
                            "home": self._home_away,
                            "clients": self._last_client_state,
                            "signals": signals,
                            "updated_at": datetime.now(UTC).isoformat(),
                        },
                    )
                    self._last_error = None
                    logger.debug(
                        "UniFi Network: %d clients, %d signals, home=%s", len(clients), len(signals), self._home_away
                    )

            except Exception as e:
                self._last_error = str(e)
                logger.warning("UniFi Network poll error: %s", e)

            await asyncio.sleep(self._poll_interval)

    async def _protect_ws_loop(self) -> None:
        """Subscribe to UniFi Protect WebSocket for smart detect events."""
        raise NotImplementedError  # implemented in Task 6
