"""Tests for worker.main module."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.main import create_database_engine, process_local_image, start_heartbeat, upload_inductor_cache_if_needed


class TestCreateDatabaseEngine:
    async def test_uses_rds_async_creator_by_default(self):
        database_url = "postgresql+psycopg://user:pass@host:5432/dbname"
        async_creator = AsyncMock()
        engine = object()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("worker.main.create_async_creator", AsyncMock(return_value=async_creator)) as create_async_creator,
            patch("worker.main.create_async_engine", return_value=engine) as create_async_engine,
        ):
            os.environ.pop("DATABASE_LOCAL", None)
            result = await create_database_engine(database_url)

        assert result is engine
        create_async_creator.assert_awaited_once_with(database_url, bastion=None)
        create_async_engine.assert_called_once_with(database_url, pool_pre_ping=True, async_creator=async_creator)

    async def test_skips_rds_async_creator_when_database_local_is_true(self):
        database_url = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
        engine = object()

        with (
            patch.dict(os.environ, {"DATABASE_LOCAL": "true"}, clear=False),
            patch("worker.main.create_async_creator", AsyncMock()) as create_async_creator,
            patch("worker.main.create_async_engine", return_value=engine) as create_async_engine,
        ):
            result = await create_database_engine(database_url)

        assert result is engine
        create_async_creator.assert_not_awaited()
        create_async_engine.assert_called_once_with(database_url, pool_pre_ping=True)

    async def test_uses_rds_async_creator_when_database_local_is_false(self):
        database_url = "postgresql+psycopg://user:pass@host:5432/dbname"
        async_creator = AsyncMock()
        engine = object()

        with (
            patch.dict(os.environ, {"DATABASE_LOCAL": "false"}, clear=False),
            patch("worker.main.create_async_creator", AsyncMock(return_value=async_creator)) as create_async_creator,
            patch("worker.main.create_async_engine", return_value=engine) as create_async_engine,
        ):
            result = await create_database_engine(database_url)

        assert result is engine
        create_async_creator.assert_awaited_once_with(database_url, bastion=None)
        create_async_engine.assert_called_once_with(database_url, pool_pre_ping=True, async_creator=async_creator)


class TestUploadInductorCacheIfNeeded:
    async def test_no_cache_dir_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TORCHINDUCTOR_CACHE_DIR", None)
            await upload_inductor_cache_if_needed()
            # Should return immediately without error

    async def test_downloaded_marker_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / ".downloaded").touch()
            (Path(tmpdir) / ".cache-key").write_text("test-key")
            with patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": tmpdir}):
                await upload_inductor_cache_if_needed()
                # Should skip upload

    async def test_no_cache_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": tmpdir}):
                await upload_inductor_cache_if_needed()
                # Should skip upload (no .cache-key)

    async def test_no_s3_bucket_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / ".cache-key").write_text("test-key")
            with (
                patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": tmpdir}),
                patch("worker.main.APP_DIR", tmpdir),
            ):
                await upload_inductor_cache_if_needed()
                # Should skip (no S3 config)


class TestStartHeartbeat:
    async def test_heartbeat_executes(self):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        from uuid import UUID

        worker_id = UUID("12345678-1234-5678-1234-567812345678")

        # Run heartbeat briefly then cancel
        task = asyncio.create_task(start_heartbeat(factory, worker_id))
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_session.execute.assert_called()
        mock_session.commit.assert_called()

    async def test_heartbeat_handles_error(self, capsys):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("db error"))

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        from uuid import UUID

        worker_id = UUID("12345678-1234-5678-1234-567812345678")

        task = asyncio.create_task(start_heartbeat(factory, worker_id))
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        captured = capsys.readouterr()
        assert "Failed to update heartbeat" in captured.out


class TestUploadInductorCacheWithS3:
    async def test_upload_success(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            (Path(cache_dir) / ".cache-key").write_text("test-key-123")
            # Add some cache content
            (Path(cache_dir) / "kernel.o").write_text("compiled kernel")

            wheels_dir = os.path.join(tmpdir, "wheels")
            os.makedirs(wheels_dir)
            (Path(wheels_dir) / ".s3-bucket").write_text("my-bucket")
            (Path(wheels_dir) / ".s3-prefix").write_text("prefix")

            mock_tar = AsyncMock()
            mock_tar.wait = AsyncMock(return_value=None)
            mock_tar.returncode = 0

            mock_s3 = AsyncMock()
            mock_s3.wait = AsyncMock(return_value=None)
            mock_s3.returncode = 0

            call_count = [0]

            async def mock_subprocess(*args):
                call_count[0] += 1
                if call_count[0] == 1:
                    return mock_tar
                return mock_s3

            with (
                patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": cache_dir}),
                patch("worker.main.APP_DIR", tmpdir),
                patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess),
            ):
                await upload_inductor_cache_if_needed()

            captured = capsys.readouterr()
            assert "Cache uploaded" in captured.out

    async def test_upload_tar_failure(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            (Path(cache_dir) / ".cache-key").write_text("test-key")

            wheels_dir = os.path.join(tmpdir, "wheels")
            os.makedirs(wheels_dir)
            (Path(wheels_dir) / ".s3-bucket").write_text("my-bucket")

            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=None)
            mock_proc.returncode = 1  # Failure

            with (
                patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": cache_dir}),
                patch("worker.main.APP_DIR", tmpdir),
                patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            ):
                await upload_inductor_cache_if_needed()

            captured = capsys.readouterr()
            assert "Cache upload failed" in captured.out

    async def test_no_s3_prefix(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            (Path(cache_dir) / ".cache-key").write_text("test-key")

            wheels_dir = os.path.join(tmpdir, "wheels")
            os.makedirs(wheels_dir)
            (Path(wheels_dir) / ".s3-bucket").write_text("my-bucket")
            # No .s3-prefix file

            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=None)
            mock_proc.returncode = 0

            with (
                patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": cache_dir}),
                patch("worker.main.APP_DIR", tmpdir),
                patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            ):
                await upload_inductor_cache_if_needed()

            captured = capsys.readouterr()
            assert "Cache uploaded" in captured.out


class TestProcessLocalImage:
    async def test_invalid_image_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an invalid image
            img_path = os.path.join(tmpdir, "bad.png")
            with open(img_path, "w") as f:
                f.write("not an image")

            mock_client = AsyncMock()
            mock_worker = MagicMock()

            with pytest.raises(ValueError, match="Failed to read image"):
                await process_local_image(mock_client, mock_worker, img_path)
