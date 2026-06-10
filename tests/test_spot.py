"""Tests for worker.worker.spot module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

from worker.worker.spot import (
    IMDS_BASE,
    IMDS_SPOT_ACTION_URL,
    IMDS_TOKEN_URL,
    SpotInterruptionMonitor,
)


class TestIsEc2Instance:
    async def test_ec2_imdsv2_success(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, payload="token123")
            result = await SpotInterruptionMonitor.is_ec2_instance()
            assert result is True

    async def test_ec2_imdsv1_fallback(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, status=500)
            m.get(f"{IMDS_BASE}/latest/meta-data/", payload="data")
            result = await SpotInterruptionMonitor.is_ec2_instance()
            assert result is True

    async def test_not_ec2(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, exception=asyncio.TimeoutError())
            m.get(f"{IMDS_BASE}/latest/meta-data/", exception=asyncio.TimeoutError())
            result = await SpotInterruptionMonitor.is_ec2_instance()
            assert result is False


class TestSpotInterruptionMonitor:
    def test_init(self):
        callback = MagicMock()
        monitor = SpotInterruptionMonitor(on_interruption=callback)
        assert monitor._running is False
        assert monitor._token is None

    def test_stop(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._running = True
        monitor.stop()
        assert monitor._running is False

    async def test_get_token(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, body="mytoken123")
            token = await monitor._get_token()
            assert token == "mytoken123"

    async def test_get_token_cached(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "cached_token"
        token = await monitor._get_token()
        assert token == "cached_token"

    async def test_get_token_failure(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, exception=asyncio.TimeoutError())
            token = await monitor._get_token()
            assert token is None

    async def test_check_interruption_none(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, status=404)
            result = await monitor._check_interruption()
            assert result is None

    async def test_check_interruption_found(self):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        action_data = {"action": "terminate", "time": "2024-01-01T00:00:00Z"}
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, body=json.dumps(action_data))
            result = await monitor._check_interruption()
            assert result == action_data

    async def test_check_interruption_network_error(self, capsys):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, exception=asyncio.TimeoutError())
            result = await monitor._check_interruption()
            assert result is None
            captured = capsys.readouterr()
            assert "IMDS temporarily unreachable" in captured.out

    async def test_check_interruption_error_logged_once(self, capsys):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        monitor._imds_error_logged = True
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, exception=asyncio.TimeoutError())
            await monitor._check_interruption()
            captured = capsys.readouterr()
            # Second error should not be logged again
            assert "IMDS temporarily unreachable" not in captured.out

    async def test_check_interruption_connection_restored(self, capsys):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        monitor._imds_error_logged = True
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, status=404)
            await monitor._check_interruption()
            assert monitor._imds_error_logged is False
            captured = capsys.readouterr()
            assert "IMDS connection restored" in captured.out

    async def test_start_calls_callback_on_interruption(self, capsys):
        callback = MagicMock()
        monitor = SpotInterruptionMonitor(on_interruption=callback)
        monitor._token = "token"

        action_data = {"action": "terminate", "time": "2024-01-01T00:00:00Z"}
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, body=json.dumps(action_data))
            await monitor.start()

        callback.assert_called_once()
        assert monitor._running is False

    async def test_start_handles_callback_error(self, capsys):
        callback = MagicMock(side_effect=RuntimeError("callback failed"))
        monitor = SpotInterruptionMonitor(on_interruption=callback)
        monitor._token = "token"

        action_data = {"action": "terminate", "time": "2024-01-01T00:00:00Z"}
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, body=json.dumps(action_data))
            await monitor.start()

        captured = capsys.readouterr()
        assert "Error calling interruption callback" in captured.out

    async def test_check_interruption_invalid_json(self, capsys):
        monitor = SpotInterruptionMonitor(on_interruption=MagicMock())
        monitor._token = "token"
        with aioresponses() as m:
            m.get(IMDS_SPOT_ACTION_URL, body="not json", status=200)
            result = await monitor._check_interruption()
            assert result is None
            captured = capsys.readouterr()
            assert "Invalid JSON" in captured.out
