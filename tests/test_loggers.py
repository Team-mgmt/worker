"""Tests for worker.loggers module."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from worker.loggers.base import BaseLogger
from worker.loggers.console import ConsoleLogger
from worker.loggers.database import DatabaseLogger


class TestBaseLogger:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(NotImplementedError):
            BaseLogger()

    async def test_abstract_methods_raise(self):
        # Create a subclass that doesn't implement methods
        class BadLogger(BaseLogger):
            def __init__(self):
                pass  # Skip parent check

        logger = BadLogger()
        with pytest.raises(NotImplementedError):
            await logger.info("test")
        with pytest.raises(NotImplementedError):
            await logger.warn("test")
        with pytest.raises(NotImplementedError):
            await logger.error("test")


class TestConsoleLogger:
    async def test_info(self, capsys):
        logger = ConsoleLogger()
        await logger.info("hello")
        captured = capsys.readouterr()
        assert "[INFO] hello" in captured.out

    async def test_warn(self, capsys):
        logger = ConsoleLogger()
        await logger.warn("warning")
        captured = capsys.readouterr()
        assert "[WARN] warning" in captured.out

    async def test_error(self, capsys):
        logger = ConsoleLogger()
        await logger.error("err")
        captured = capsys.readouterr()
        assert "[ERROR] err" in captured.out


class TestDatabaseLogger:
    @pytest.fixture
    def mock_session_factory(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        return factory, session

    def test_init(self, mock_session_factory):
        factory, _ = mock_session_factory
        job_id = UUID("12345678-1234-5678-1234-567812345678")
        request_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        worker_id = UUID("11111111-1111-1111-1111-111111111111")

        logger = DatabaseLogger(factory, job_id, request_id, worker_id)
        assert logger.job_id == job_id
        assert logger.scan_request_id == request_id
        assert logger.worker_id == worker_id

    async def test_info_logs_to_db(self, mock_session_factory, capsys):
        factory, session = mock_session_factory
        job_id = UUID("12345678-1234-5678-1234-567812345678")
        logger = DatabaseLogger(factory, job_id, job_id, job_id)

        await logger.info("test message")
        session.add.assert_called_once()
        session.commit.assert_called_once()

        # Also prints to stdout
        captured = capsys.readouterr()
        assert "[INFO]" in captured.out
        assert "test message" in captured.out

    async def test_warn_logs_to_db(self, mock_session_factory, capsys):
        factory, session = mock_session_factory
        job_id = UUID("12345678-1234-5678-1234-567812345678")
        logger = DatabaseLogger(factory, job_id, job_id, job_id)

        await logger.warn("warn msg")
        session.add.assert_called_once()
        captured = capsys.readouterr()
        assert "[WARN]" in captured.out

    async def test_error_logs_to_db(self, mock_session_factory, capsys):
        factory, session = mock_session_factory
        job_id = UUID("12345678-1234-5678-1234-567812345678")
        logger = DatabaseLogger(factory, job_id, job_id, job_id)

        await logger.error("error msg")
        session.add.assert_called_once()
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out

    async def test_log_entry_fields(self, mock_session_factory):
        factory, session = mock_session_factory
        job_id = UUID("12345678-1234-5678-1234-567812345678")
        request_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        worker_id = UUID("11111111-1111-1111-1111-111111111111")
        logger = DatabaseLogger(factory, job_id, request_id, worker_id)

        await logger.info("check fields")
        log_entry = session.add.call_args[0][0]
        assert log_entry.job_id == job_id
        assert log_entry.scan_request_id == request_id
        assert log_entry.worker_id == worker_id
        assert log_entry.log_level == "INFO"
        assert log_entry.message == "check fields"
