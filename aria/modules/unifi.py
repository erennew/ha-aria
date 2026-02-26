"""UniFi Network + Protect presence signals for ARIA.

Two signal pipelines sharing one aiohttp session:
- Network: REST polling /proxy/network/api/s/{site}/stat/sta (WiFi clients)
- Protect: uiprotect WebSocket (smart detect events + face thumbnails)

Auth: X-API-Key header. ssl=False for Dream Machine self-signed cert.
"""

import asyncio
import json
import logging
import os
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
            await self._session.close()
            self._session = None
        if self._protect_client:
            try:
                await self._protect_client.disconnect()
            except Exception as e:
                logger.debug("UniFi Protect: disconnect error during shutdown — %s", e)
            self._protect_client = None
        logger.info("UniFi module shut down")

    # ── Stub loops (implemented in Tasks 5, 6) ────────────────────────

    async def _network_poll_loop(self) -> None:
        """Poll UniFi Network for WiFi client state every poll_interval_s."""
        raise NotImplementedError  # implemented in Task 5

    async def _protect_ws_loop(self) -> None:
        """Subscribe to UniFi Protect WebSocket for smart detect events."""
        raise NotImplementedError  # implemented in Task 6
