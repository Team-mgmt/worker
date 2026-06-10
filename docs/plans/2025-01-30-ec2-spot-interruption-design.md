# EC2 Spot Interruption Monitor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add EC2 Spot Instance interruption notice detection to trigger graceful shutdown when AWS sends a 2-minute warning.

**Architecture:** A `SpotInterruptionMonitor` class polls the EC2 Instance Metadata Service (IMDS) every 5 seconds. At startup, it probes IMDS to detect if running on EC2; if not, it silently disables itself. When an interruption notice is detected, it calls the provided callback to trigger graceful shutdown.

**Tech Stack:** Python 3.12+, aiohttp (via aioboto3), asyncio

---

## Task 1: Create SpotInterruptionMonitor class

**Files:**
- Create: `worker/worker/spot.py`

**Step 1: Create the spot.py module with the SpotInterruptionMonitor class**

```python
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
        headers = {}

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
```

**Step 2: Verify the module is syntactically correct**

Run: `cd /home/swjeon/projects/qmr-worker && uv run python -c "from worker.worker.spot import SpotInterruptionMonitor; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add worker/worker/spot.py
git commit -m "feat: add SpotInterruptionMonitor for EC2 spot instance handling"
```

---

## Task 2: Integrate SpotInterruptionMonitor into main.py

**Files:**
- Modify: `worker/main.py:31-32` (imports)
- Modify: `worker/main.py:161-169` (after signal handlers, before health server)

**Step 1: Add import for SpotInterruptionMonitor**

In `worker/main.py`, add the import after line 31:

```python
from .worker import ScanWorker
from .worker.spot import SpotInterruptionMonitor
```

**Step 2: Add spot monitor initialization after signal handlers**

In `worker/main.py`, after the signal handler registration (line 161) and before health server start (line 163), add:

```python
        # Register signal handlers for graceful shutdown (ECS sends SIGTERM)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.request_shutdown)

        # EC2 Spot interruption monitor (only starts if on EC2)
        spot_monitor = SpotInterruptionMonitor(on_interruption=worker.request_shutdown)
        spot_task: asyncio.Task | None = None
        if await SpotInterruptionMonitor.is_ec2_instance():
            spot_task = asyncio.create_task(spot_monitor.start())
            print("[Spot] Interruption monitor started")
        else:
            print("[Spot] Not running on EC2, monitor disabled")

        # Start health check server as a background task
```

**Step 3: Add spot_task cleanup at the end of main()**

In `worker/main.py`, modify the cleanup section (around line 194-195) to include spot_task:

```python
        if spot_task:
            spot_task.cancel()
        heartbeat_task.cancel()
        health_task.cancel()
```

**Step 4: Run type checker**

Run: `cd /home/swjeon/projects/qmr-worker && uv run python -m mypy worker/main.py worker/worker/spot.py --show-error-context`
Expected: No errors (or only pre-existing unrelated errors)

**Step 5: Commit**

```bash
git add worker/main.py
git commit -m "feat: integrate SpotInterruptionMonitor into worker startup"
```

---

## Task 3: Run lint and verify

**Step 1: Run ruff linter**

Run: `cd /home/swjeon/projects/qmr-worker && uv run python -m ruff check worker/`
Expected: No new errors

**Step 2: Run mypy type checker**

Run: `cd /home/swjeon/projects/qmr-worker && uv run python -m mypy worker/ --show-error-context`
Expected: No new errors

**Step 3: Test import and basic instantiation**

Run: `cd /home/swjeon/projects/qmr-worker && uv run python -c "from worker.worker.spot import SpotInterruptionMonitor; m = SpotInterruptionMonitor(lambda: print('shutdown')); print('Monitor created OK')"`
Expected: `Monitor created OK`

---

## Summary

After completing all tasks:
- `worker/worker/spot.py` - New module with `SpotInterruptionMonitor` class
- `worker/main.py` - Imports and integrates the monitor as a background task

The monitor will:
- Auto-detect EC2 at startup (500ms timeout)
- If on EC2: poll IMDS every 5 seconds for interruption notices
- If not on EC2: print log message and skip (no background task)
- On interruption: call `worker.request_shutdown()` and stop polling
