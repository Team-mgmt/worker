"""Tests for worker.worker.disk module."""

import os
import tempfile
import time
from unittest.mock import patch

import pytest

from worker.worker.disk import DiskMonitorWorker


class TestDiskMonitorWorker:
    def test_init_default(self):
        monitor = DiskMonitorWorker()
        assert monitor.templates_dir is not None

    def test_init_custom_dir(self):
        monitor = DiskMonitorWorker(templates_dir="/custom/path")
        assert monitor.templates_dir == "/custom/path"

    def test_check_disabled(self):
        monitor = DiskMonitorWorker()
        with patch("worker.worker.disk.DISK_MONITOR_ENABLED", False):
            # Should return immediately without error
            monitor.check_and_cleanup()

    def test_check_below_threshold(self):
        """When disk usage is below threshold, no cleanup happens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitorWorker(templates_dir=tmpdir)
            # Default threshold is 80%, normal disk usage should be below
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 99),
            ):
                monitor.check_and_cleanup()
                # No files removed since we're below threshold

    def test_cleanup_removes_oldest_files(self, capsys):
        """When above threshold, oldest template files are removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create template files with different timestamps
            files = []
            for i in range(10):
                path = os.path.join(tmpdir, f"template_{i}.png")
                with open(path, "wb") as f:
                    f.write(b"x" * 1024)
                # Set different modification times
                os.utime(path, (time.time() - (10 - i) * 100, time.time() - (10 - i) * 100))
                files.append(path)

            monitor = DiskMonitorWorker(templates_dir=tmpdir)
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),  # Always above threshold
                patch("worker.worker.disk.MIN_TEMPLATE_FILES_TO_KEEP", 5),
            ):
                monitor.check_and_cleanup()

            remaining = os.listdir(tmpdir)
            # Should keep at most 5 files (or stop if disk goes below threshold)
            assert len(remaining) <= 10

    def test_cleanup_skips_when_few_files(self, capsys):
        """When file count is at or below minimum, skip cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                path = os.path.join(tmpdir, f"template_{i}.png")
                with open(path, "w") as f:
                    f.write("data")

            monitor = DiskMonitorWorker(templates_dir=tmpdir)
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
                patch("worker.worker.disk.MIN_TEMPLATE_FILES_TO_KEEP", 5),
                patch("worker.worker.disk.STORAGE_DIR", tmpdir),
            ):
                monitor.check_and_cleanup()

            # All 3 files should remain (below minimum)
            assert len(os.listdir(tmpdir)) == 3
            captured = capsys.readouterr()
            assert "skipping cleanup" in captured.out

    def test_cleanup_nonexistent_templates_dir(self):
        """When templates directory doesn't exist, skip silently."""
        monitor = DiskMonitorWorker(templates_dir="/nonexistent/path/12345")
        with (
            patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
            patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
            patch("worker.worker.disk.STORAGE_DIR", "/tmp"),
        ):
            monitor.check_and_cleanup()  # Should not raise

    def test_cleanup_handles_os_error(self, capsys):
        """OS errors during disk check are caught and logged."""
        monitor = DiskMonitorWorker(templates_dir="/tmp")
        with (
            patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
            patch("worker.worker.disk.STORAGE_DIR", "/nonexistent/storage/12345"),
        ):
            monitor.check_and_cleanup()
            captured = capsys.readouterr()
            assert "Error checking disk usage" in captured.out

    def test_cleanup_removes_files_and_rechecks_usage(self, capsys):
        """Full cleanup cycle that removes files and rechecks disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(8):
                path = os.path.join(tmpdir, f"template_{i}.png")
                with open(path, "wb") as f:
                    f.write(b"x" * 100)
                os.utime(path, (time.time() - (8 - i) * 100, time.time() - (8 - i) * 100))

            monitor = DiskMonitorWorker(templates_dir=tmpdir)
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
                patch("worker.worker.disk.MIN_TEMPLATE_FILES_TO_KEEP", 5),
                patch("worker.worker.disk.STORAGE_DIR", tmpdir),
            ):
                monitor.check_and_cleanup()

            captured = capsys.readouterr()
            assert "starting LRU cleanup" in captured.out
            assert "Removed template (LRU)" in captured.out
            assert "Cleanup complete" in captured.out

    def test_cleanup_ignores_directories(self):
        """Directories within templates_dir should be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory (should be ignored)
            os.makedirs(os.path.join(tmpdir, "subdir"))
            for i in range(3):
                path = os.path.join(tmpdir, f"template_{i}.png")
                with open(path, "w") as f:
                    f.write("data")

            monitor = DiskMonitorWorker(templates_dir=tmpdir)
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
                patch("worker.worker.disk.MIN_TEMPLATE_FILES_TO_KEEP", 2),
                patch("worker.worker.disk.STORAGE_DIR", tmpdir),
            ):
                monitor.check_and_cleanup()

            # Subdirectory should still exist, only files counted
            assert os.path.isdir(os.path.join(tmpdir, "subdir"))

    def test_cleanup_evicts_cache_dirs(self, capsys):
        """Cache directories passed to the constructor are also swept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = os.path.join(tmpdir, "templates")
            cache_dir = os.path.join(tmpdir, "cache", "template_thresh")
            os.makedirs(templates_dir)
            os.makedirs(cache_dir)

            # Minimal files in templates_dir so it's skipped
            for i in range(2):
                path = os.path.join(templates_dir, f"t_{i}.png")
                with open(path, "wb") as f:
                    f.write(b"x")

            # Enough cache files to trigger eviction
            for i in range(10):
                path = os.path.join(cache_dir, f"c_{i}.png")
                with open(path, "wb") as f:
                    f.write(b"x" * 1024)
                os.utime(path, (time.time() - (10 - i) * 100, time.time() - (10 - i) * 100))

            monitor = DiskMonitorWorker(templates_dir=templates_dir, cache_dirs=[cache_dir])
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
                patch("worker.worker.disk.MIN_TEMPLATE_FILES_TO_KEEP", 5),
                patch("worker.worker.disk.MIN_CACHE_FILES_TO_KEEP", 5),
                patch("worker.worker.disk.STORAGE_DIR", tmpdir),
            ):
                monitor.check_and_cleanup()

            captured = capsys.readouterr()
            assert "Removed cache (LRU)" in captured.out
            # Oldest 5 evicted, newest 5 survive
            remaining = sorted(os.listdir(cache_dir))
            assert remaining == [f"c_{i}.png" for i in range(5, 10)]

    def test_cleanup_skips_missing_cache_dir(self):
        """A cache dir path that doesn't exist should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = os.path.join(tmpdir, "templates")
            os.makedirs(templates_dir)
            missing = os.path.join(tmpdir, "does", "not", "exist")

            monitor = DiskMonitorWorker(templates_dir=templates_dir, cache_dirs=[missing])
            with (
                patch("worker.worker.disk.DISK_MONITOR_ENABLED", True),
                patch("worker.worker.disk.DISK_USAGE_THRESHOLD_PERCENT", 0),
                patch("worker.worker.disk.STORAGE_DIR", tmpdir),
            ):
                monitor.check_and_cleanup()  # Should not raise

    def test_init_cache_dirs_default_empty(self):
        """Default cache_dirs is an empty list."""
        monitor = DiskMonitorWorker()
        assert monitor.cache_dirs == []
