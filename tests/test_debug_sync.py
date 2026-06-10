"""Tests for DebugSyncWorker."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker import paths
from worker.debug_sync import (
    DEBUG_LOCAL_RETENTION_ENV,
    DEBUG_S3_BUCKET_ENV,
    DEBUG_S3_PREFIX_ENV,
    DEBUG_SYNC_INTERVAL_ENV,
    DebugSyncWorker,
)


@pytest.fixture
def storage_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "DEBUG_DIR", str(tmp_path / "debug"))
    # The module captured DEBUG_DIR at import time, so patch the captured ref too.
    monkeypatch.setattr("worker.debug_sync.DEBUG_DIR", str(tmp_path / "debug"))
    (tmp_path / "debug").mkdir()
    return tmp_path


def _clear_env(monkeypatch):
    for var in (
        DEBUG_S3_BUCKET_ENV,
        DEBUG_S3_PREFIX_ENV,
        DEBUG_SYNC_INTERVAL_ENV,
        DEBUG_LOCAL_RETENTION_ENV,
    ):
        monkeypatch.delenv(var, raising=False)


def test_sync_disabled_when_bucket_unset(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    worker = DebugSyncWorker()
    assert worker.sync_enabled is False
    assert worker.bucket == ""


def test_sync_destination_includes_prefix(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    monkeypatch.setenv(DEBUG_S3_PREFIX_ENV, "scans/debug")
    worker = DebugSyncWorker()
    assert worker.sync_enabled is True
    assert worker.s3_destination == "s3://my-bucket/scans/debug/"


def test_sync_destination_strips_slashes(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    monkeypatch.setenv(DEBUG_S3_PREFIX_ENV, "/leading/")
    worker = DebugSyncWorker()
    assert worker.s3_destination == "s3://my-bucket/leading/"


def test_sync_destination_no_prefix(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    monkeypatch.setenv(DEBUG_S3_PREFIX_ENV, "")
    worker = DebugSyncWorker()
    assert worker.s3_destination == "s3://my-bucket/"


def test_prune_removes_old_files_keeps_fresh(storage_tmp):
    debug_root = storage_tmp / "debug"
    job_dir = debug_root / "req-1" / "job-1"
    job_dir.mkdir(parents=True)
    old = job_dir / "old.png"
    fresh = job_dir / "fresh.png"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    # Backdate `old` 10 hours; cutoff 1 hour.
    backdated = time.time() - 10 * 3600
    os.utime(old, (backdated, backdated))

    DebugSyncWorker._prune_blocking(time.time() - 3600)

    assert not old.exists()
    assert fresh.exists()


def test_prune_removes_empty_dirs_after_files(storage_tmp):
    debug_root = storage_tmp / "debug"
    job_dir = debug_root / "req-1" / "job-1"
    job_dir.mkdir(parents=True)
    target = job_dir / "stale.png"
    target.write_bytes(b"x")
    backdated = time.time() - 10 * 3600
    os.utime(target, (backdated, backdated))

    DebugSyncWorker._prune_blocking(time.time() - 3600)

    assert not target.exists()
    assert not job_dir.exists()
    assert not (debug_root / "req-1").exists()


@pytest.mark.asyncio
async def test_sync_once_invokes_aws_with_argv(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    monkeypatch.setenv(DEBUG_S3_PREFIX_ENV, "debug")
    worker = DebugSyncWorker()

    fake_proc = AsyncMock()
    fake_proc.communicate = AsyncMock(return_value=(b"upload: foo.png\n", b""))
    fake_proc.returncode = 0

    with patch("worker.debug_sync.asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)) as spawn:
        await worker._sync_once()

    spawn.assert_awaited_once()
    args = spawn.await_args.args
    assert args[0] == "aws"
    # SRC must be the local debug dir, DEST must be the s3:// URI — never inverted.
    # This locks in upload-only direction (sync flows SRC→DEST only).
    assert args[1:5] == ("s3", "sync", str(storage_tmp / "debug"), "s3://my-bucket/debug/")
    assert "--no-progress" in args
    assert "--size-only" in args
    assert "--delete" not in args  # local prune must NOT propagate to S3


@pytest.mark.asyncio
async def test_sync_once_terminates_subprocess_on_cancel(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    worker = DebugSyncWorker()

    fake_proc = AsyncMock()
    fake_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.terminate = MagicMock()
    fake_proc.kill = MagicMock()
    fake_proc.returncode = None

    with patch("worker.debug_sync.asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
        with pytest.raises(asyncio.CancelledError):
            await worker._sync_once()

    fake_proc.terminate.assert_called_once()
    fake_proc.kill.assert_not_called()  # graceful terminate succeeded


@pytest.mark.asyncio
async def test_sync_once_kills_subprocess_when_terminate_hangs(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    worker = DebugSyncWorker()

    fake_proc = AsyncMock()
    fake_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
    # First wait() (after terminate) hangs forever; second wait() (after kill) returns.
    wait_calls = {"n": 0}

    async def hanging_then_returning_wait() -> int:
        wait_calls["n"] += 1
        if wait_calls["n"] == 1:
            await asyncio.sleep(60)
        return 0

    fake_proc.wait = hanging_then_returning_wait
    fake_proc.terminate = MagicMock()
    fake_proc.kill = MagicMock()
    fake_proc.returncode = None

    with patch("worker.debug_sync.asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
        # Override the 5s wait_for inside _terminate_subprocess so the test
        # itself doesn't sit for 5 real seconds.
        original_wait_for = asyncio.wait_for

        async def fast_wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
            return await original_wait_for(awaitable, timeout=0.05)

        with patch("worker.debug_sync.asyncio.wait_for", new=fast_wait_for):
            with pytest.raises(asyncio.CancelledError):
                await worker._sync_once()

    fake_proc.terminate.assert_called_once()
    fake_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_sync_once_skips_when_dir_missing(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_S3_BUCKET_ENV, "my-bucket")
    # Remove the debug dir set up by the fixture.
    (storage_tmp / "debug").rmdir()
    worker = DebugSyncWorker()
    with patch("worker.debug_sync.asyncio.create_subprocess_exec", new=AsyncMock()) as spawn:
        await worker._sync_once()
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_start_skips_when_no_bucket_no_retention(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(DEBUG_LOCAL_RETENTION_ENV, "0")
    worker = DebugSyncWorker()
    await worker.start()
    assert worker._task is None
    await worker.stop()  # idempotent no-op


@pytest.mark.asyncio
async def test_start_runs_prune_only_when_no_bucket(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    # Retention set so the prune-only loop is justified, sub-second interval to
    # observe a cycle quickly.
    monkeypatch.setenv(DEBUG_LOCAL_RETENTION_ENV, "1")
    monkeypatch.setenv(DEBUG_SYNC_INTERVAL_ENV, "1")
    worker = DebugSyncWorker()

    # Drop a stale file that the loop should sweep on its first cycle.
    stale = storage_tmp / "debug" / "stale.png"
    stale.write_bytes(b"x")
    backdated = time.time() - 10 * 3600
    os.utime(stale, (backdated, backdated))

    await worker.start()
    try:
        # Yield to the event loop so the first cycle runs.
        for _ in range(20):
            await asyncio.sleep(0.05)
            if not stale.exists():
                break
        assert not stale.exists()
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent(storage_tmp, monkeypatch):
    _clear_env(monkeypatch)
    worker = DebugSyncWorker()
    await worker.stop()
    await worker.stop()  # second call does nothing