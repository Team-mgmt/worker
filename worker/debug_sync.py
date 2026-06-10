"""Periodic background sync of the local debug dir to S3.

Workers write debug artifacts to ``$STORAGE_DIR/debug/<request>/<job>/``.
``DebugSyncWorker`` runs as a long-lived asyncio task started by
``ScanWorker.start()``. It invokes ``aws s3 sync`` via
``asyncio.create_subprocess_exec`` (argv list — no shell, so the
ALLOW_DEBUG/ENABLE_DEBUG/bucket env strings cannot inject commands)
on a configurable interval, then prunes any local files older than
the retention window.

Knobs (env, settable from SSM):

- ``DEBUG_S3_BUCKET``: destination bucket. If unset, sync is disabled but
  the prune loop still runs so the disk does not fill with leftover dumps.
- ``DEBUG_S3_PREFIX``: key prefix under the bucket. Defaults to ``"debug"``.
- ``DEBUG_SYNC_INTERVAL_SECONDS``: cadence between sync cycles (default 300).
- ``DEBUG_LOCAL_RETENTION_HOURS``: delete local files whose mtime is older
  than this. Defaults to 24. Set to 0 to keep everything locally forever.

Shelling out to ``aws s3 sync`` is intentional: it parallelizes uploads,
diffs by checksum, and is well-tuned for many small files — replicating
that on top of the boto3 client would duplicate solved work. Requires
the ``aws`` CLI on the worker host.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path

from .paths import DEBUG_DIR

DEBUG_S3_BUCKET_ENV = "DEBUG_S3_BUCKET"
DEBUG_S3_PREFIX_ENV = "DEBUG_S3_PREFIX"
DEBUG_SYNC_INTERVAL_ENV = "DEBUG_SYNC_INTERVAL_SECONDS"
DEBUG_LOCAL_RETENTION_ENV = "DEBUG_LOCAL_RETENTION_HOURS"

DEFAULT_SYNC_INTERVAL_SECONDS = 300
DEFAULT_LOCAL_RETENTION_HOURS = 24.0


class DebugSyncWorker:
    """Background asyncio task: periodic ``aws s3 sync`` + local prune."""

    def __init__(self) -> None:
        self.bucket = os.getenv(DEBUG_S3_BUCKET_ENV, "").strip()
        self.prefix = os.getenv(DEBUG_S3_PREFIX_ENV, "debug").strip("/")
        self.interval_seconds = max(1, int(os.getenv(DEBUG_SYNC_INTERVAL_ENV, str(DEFAULT_SYNC_INTERVAL_SECONDS))))
        retention_hours = float(os.getenv(DEBUG_LOCAL_RETENTION_ENV, str(DEFAULT_LOCAL_RETENTION_HOURS)))
        self.retention_seconds = int(retention_hours * 3600)
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

    @property
    def sync_enabled(self) -> bool:
        return bool(self.bucket)

    @property
    def s3_destination(self) -> str:
        if self.prefix:
            return f"s3://{self.bucket}/{self.prefix}/"
        return f"s3://{self.bucket}/"

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        if not self.sync_enabled and self.retention_seconds <= 0:
            print("[DebugSync] no bucket and no retention configured; sync loop not started")
            return
        if not self.sync_enabled:
            print(f"[DebugSync] {DEBUG_S3_BUCKET_ENV} unset; running prune-only loop")
        else:
            print(
                f"[DebugSync] sync every {self.interval_seconds}s to {self.s3_destination}; "
                f"local retention={self.retention_seconds // 3600}h"
            )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.sync_enabled:
                    await self._sync_once()
                await self._prune_once()
            except Exception as exc:
                # Debug sync failures must never crash the worker.
                print(f"[DebugSync] cycle failed: {type(exc).__name__}: {exc}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _sync_once(self) -> None:
        if not os.path.isdir(DEBUG_DIR):
            return
        # argv list (not a shell string) so bucket/prefix env values are
        # passed as literal arguments rather than parsed by /bin/sh.
        #
        # Direction is locked: SRC is the local DEBUG_DIR, DEST is the
        # s3:// URI — `aws s3 sync` only flows SRC→DEST, so this command
        # exclusively uploads. We never invoke it with the s3:// URI as
        # SRC (which would be the only way to download). `--delete` is
        # deliberately omitted: files we prune locally past retention
        # must remain in S3. `--size-only` skips re-uploads when only
        # mtime drifted, which keeps idempotent re-runs cheap.
        argv = [
            "aws",
            "s3",
            "sync",
            DEBUG_DIR,
            self.s3_destination,
            "--no-progress",
            "--size-only",
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            # Worker shutdown cancelled the background task while the CLI
            # was running. Without explicit teardown, the subprocess
            # would survive as an orphan and keep uploading — wasting
            # bandwidth and racing against the next worker startup.
            await self._terminate_subprocess(proc)
            raise
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()[:500]
            print(f"[DebugSync] aws s3 sync failed (rc={proc.returncode}): {err}")
            return
        line_count = len([line for line in stdout.splitlines() if line.strip()])
        if line_count > 0:
            print(f"[DebugSync] synced {line_count} files to {self.s3_destination}")

    @staticmethod
    async def _terminate_subprocess(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()

    async def _prune_once(self) -> None:
        if self.retention_seconds <= 0:
            return
        cutoff = time.time() - self.retention_seconds
        await asyncio.to_thread(self._prune_blocking, cutoff)

    @staticmethod
    def _prune_blocking(cutoff: float) -> None:
        root = Path(DEBUG_DIR)
        if not root.is_dir():
            return
        deleted = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                print(f"[DebugSync] prune unlink failed for {path}: {exc}")
        # Bottom-up empty-dir cleanup so per-job dirs disappear once
        # their last file expires.
        for path in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        if deleted > 0:
            print(f"[DebugSync] pruned {deleted} files older than retention")
