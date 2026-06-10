"""Tests for worker.health module."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from worker.health import create_health_app


def _make_worker(ready=True, last_activity=None):
    worker = MagicMock()
    worker.is_ready.return_value = ready
    if last_activity is None:
        last_activity = time.time()
    worker.get_last_activity_time = AsyncMock(return_value=last_activity)
    return worker


class TestHealthEndpoint:
    def test_health_returns_200(self):
        worker = _make_worker()
        app = create_health_app(worker)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_health_always_200_regardless_of_ready(self):
        worker = _make_worker(ready=False)
        app = create_health_app(worker)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200


class TestReadinessEndpoint:
    def test_ready_when_warmed_up_and_active(self):
        worker = _make_worker(ready=True, last_activity=time.time())
        app = create_health_app(worker)
        client = TestClient(app)
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "last_activity_seconds_ago" in data

    def test_not_ready_when_warming_up(self):
        worker = _make_worker(ready=False)
        app = create_health_app(worker)
        client = TestClient(app)
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["reason"] == "warming up"

    def test_unhealthy_when_no_activity(self):
        # Last activity was 1000 seconds ago, timeout is 300s
        worker = _make_worker(ready=True, last_activity=time.time() - 1000)
        app = create_health_app(worker)
        with patch("worker.health.HEALTH_JOB_TIMEOUT", 300):
            client = TestClient(app)
            response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "unhealthy"
        assert "no activity" in response.json()["reason"]

    def test_ready_within_timeout(self):
        worker = _make_worker(ready=True, last_activity=time.time() - 10)
        app = create_health_app(worker)
        with patch("worker.health.HEALTH_JOB_TIMEOUT", 300):
            client = TestClient(app)
            response = client.get("/ready")
        assert response.status_code == 200


class TestStartHealthServer:
    async def test_start_health_server_creates_server(self):
        from worker.health import start_health_server

        worker = _make_worker()
        # Just test that it doesn't error on creation
        # Actually starting the server would bind a port
        with patch("worker.health.uvicorn.Server") as mock_server_cls:
            mock_instance = AsyncMock()
            mock_server_cls.return_value = mock_instance
            await start_health_server(worker)
            mock_instance.serve.assert_called_once()
