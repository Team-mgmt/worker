import os
import time
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from .worker import ScanWorker

HEALTH_JOB_TIMEOUT = int(os.getenv("HEALTH_JOB_TIMEOUT", "300"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))


def create_health_app(worker: "ScanWorker") -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health_check():
        """Liveness probe - returns 200 if the server is running."""
        return {"status": "healthy"}

    @app.get("/ready")
    async def readiness_check():
        """Readiness probe - returns 200 only when warmed up and active."""
        if not worker.is_ready():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "warming up"},
            )

        last_activity = await worker.get_last_activity_time()
        elapsed = time.time() - last_activity

        if elapsed > HEALTH_JOB_TIMEOUT:
            return JSONResponse(
                status_code=503,
                content={"status": "unhealthy", "reason": f"no activity for {elapsed:.1f}s (timeout: {HEALTH_JOB_TIMEOUT}s)"},
            )

        return {"status": "ready", "last_activity_seconds_ago": round(elapsed, 1)}

    return app


async def start_health_server(worker: "ScanWorker"):
    app = create_health_app(worker)
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
