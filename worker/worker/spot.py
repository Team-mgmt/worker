from __future__ import annotations

import asyncio
import json
from typing import Callable

import aiohttp

# IMDS endpoints
IMDS_BASE = "http://169.254.169.254"
IMDS_TOKEN_URL = f"{IMDS_BASE}/latest/api/token"
IMDS_SPOT_ACTION_URL = f"{IMDS_BASE}/latest/meta-data/spot/instance-action"

# Timeouts
IMDS_DETECT_TIMEOUT = 0.5  # 500ms for EC2 detection
IMDS_POLL_TIMEOUT = 2.0  # 2s for polling
POLL_INTERVAL = 5  # Poll every 5 seconds


class SpotInterruptionMonitor:
    """Monitors EC2 Spot Instance interruption notices via IMDS."""

    def __init__(self, on_interruption: Callable[[], None]) -> None:
        self._on_interruption = on_interruption
        self._running = False
        self._token: str | None = None
        self._imds_error_logged = False

    @staticmethod
    async def is_ec2_instance() -> bool:
        """Check if running on EC2 by probing IMDS with short timeout."""
        timeout = aiohttp.ClientTimeout(total=IMDS_DETECT_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Try IMDSv2 first
                async with session.put(
                    IMDS_TOKEN_URL,
                    headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
                ) as response:
                    if response.status == 200:
                        return True
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

        # Try IMDSv1 fallback
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{IMDS_BASE}/latest/meta-data/") as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

        return False

    async def _get_token(self) -> str | None:
        """Get or refresh IMDSv2 token."""
        if self._token:
            return self._token

        timeout = aiohttp.ClientTimeout(total=IMDS_POLL_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(
                    IMDS_TOKEN_URL,
                    headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
                ) as response:
                    if response.status == 200:
                        self._token = await response.text()
                        return self._token
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    async def _check_interruption(self) -> dict | None:
        """Check for spot interruption notice. Returns parsed JSON if found."""
        timeout = aiohttp.ClientTimeout(total=IMDS_POLL_TIMEOUT)
        headers: dict[str, str] = {}

        token = await self._get_token()
        if token:
            headers["X-aws-ec2-metadata-token"] = token

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(IMDS_SPOT_ACTION_URL, headers=headers) as response:
                    if response.status == 200:
                        text = await response.text()
                        return json.loads(text)
                    elif response.status == 404:
                        # No interruption pending - normal state
                        if self._imds_error_logged:
                            print("[Spot] IMDS connection restored")
                            self._imds_error_logged = False
                        return None
        except json.JSONDecodeError as e:
            print(f"[Spot] Invalid JSON response from IMDS: {e}")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if not self._imds_error_logged:
                print("[Spot] IMDS temporarily unreachable, will retry")
                self._imds_error_logged = True

        return None

    async def start(self) -> None:
        """Poll for interruption notices every 5 seconds."""
        self._running = True
        while self._running:
            result = await self._check_interruption()
            if result:
                action = result.get("action", "unknown")
                time = result.get("time", "unknown")
                print(f"[Spot] Interruption notice received, action={action}, time={time}")
                try:
                    self._on_interruption()
                    print("[Spot] Graceful shutdown requested")
                except Exception as e:
                    print(f"[Spot] Error calling interruption callback: {e}")
                # Stop polling after triggering shutdown
                self._running = False
                return

            await asyncio.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False
