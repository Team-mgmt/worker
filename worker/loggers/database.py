from datetime import datetime

import uuid7
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..generated.models import ScanLogs
from ..types import UUID
from .base import BaseLogger


class DatabaseLogger(BaseLogger):
    """Logger for scan jobs that persists logs to database."""

    def __init__(self, session_factory: async_sessionmaker, job_id: UUID, scan_request_id: UUID, worker_id: UUID):
        self.session_factory = session_factory
        self.job_id = job_id
        self.scan_request_id = scan_request_id
        self.worker_id = worker_id

    async def _log(self, level: str, message: str):
        print(f"[{level}][{self.job_id}] {message}")
        async with self.session_factory() as session:
            scan_log = ScanLogs(
                id=uuid7.create(),
                job_id=self.job_id,
                scan_request_id=self.scan_request_id,
                worker_id=self.worker_id,
                log_level=level,
                message=message,
                created_at=datetime.now(),
            )
            session.add(scan_log)
            await session.commit()

    async def info(self, message: str):
        await self._log("INFO", message)

    async def warn(self, message: str):
        await self._log("WARN", message)

    async def error(self, message: str):
        await self._log("ERROR", message)
