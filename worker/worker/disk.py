import os
import shutil

from ..paths import STORAGE_DIR, TEMPLATES_DIR

# Whether disk monitoring is enabled (set to "false" to disable)
DISK_MONITOR_ENABLED = os.getenv("DISK_MONITOR_ENABLED", "true").lower() != "false"
# Disk usage threshold (percentage) for triggering LRU cleanup
DISK_USAGE_THRESHOLD_PERCENT = int(os.getenv("DISK_USAGE_THRESHOLD_PERCENT", "80"))
# Minimum number of template files to keep during cleanup
MIN_TEMPLATE_FILES_TO_KEEP = int(os.getenv("MIN_TEMPLATE_FILES_TO_KEEP", "5"))
# Minimum number of files to keep in each cache directory during cleanup
MIN_CACHE_FILES_TO_KEEP = int(os.getenv("MIN_CACHE_FILES_TO_KEEP", "5"))


class DiskMonitorWorker:
    """Worker for monitoring storage disk usage and cleaning up LRU files in cleanable directories."""

    def __init__(self, templates_dir: str = TEMPLATES_DIR, cache_dirs: list[str] | None = None):
        self.templates_dir = templates_dir
        # Per-cache-dir minimum is shared; callers pass explicit paths they own.
        self.cache_dirs = list(cache_dirs) if cache_dirs else []

    def check_and_cleanup(self) -> None:
        """Monitor storage disk usage and evict LRU files from templates + cache dirs."""
        if not DISK_MONITOR_ENABLED:
            return

        try:
            usage_percent = self._disk_usage_percent()

            if usage_percent < DISK_USAGE_THRESHOLD_PERCENT:
                return

            print(f"[DiskMonitor] Disk usage at {usage_percent:.1f}%, starting LRU cleanup")

            total_removed = 0
            sweep = [(self.templates_dir, MIN_TEMPLATE_FILES_TO_KEEP, "template")]
            sweep.extend((d, MIN_CACHE_FILES_TO_KEEP, "cache") for d in self.cache_dirs)

            for dir_path, min_keep, label in sweep:
                removed, usage_percent = self._cleanup_dir(dir_path, min_keep, label)
                total_removed += removed
                if usage_percent < DISK_USAGE_THRESHOLD_PERCENT:
                    break

            print(f"[DiskMonitor] Cleanup complete, removed {total_removed} files")

        except OSError as e:
            print(f"[DiskMonitor] Error checking disk usage: {e}")

    def _cleanup_dir(self, dir_path: str, min_keep: int, label: str) -> tuple[int, float]:
        """Evict oldest files from dir_path down to min_keep. Returns (removed_count, latest_usage_percent)."""
        if not os.path.exists(dir_path):
            return 0, self._disk_usage_percent()

        files: list[tuple[str, float]] = []
        for filename in os.listdir(dir_path):
            filepath = os.path.join(dir_path, filename)
            if os.path.isfile(filepath):
                # Use mtime as proxy for LRU ordering
                files.append((filepath, os.path.getmtime(filepath)))

        if len(files) <= min_keep:
            print(f"[DiskMonitor] Only {len(files)} {label} files in {dir_path}, skipping cleanup")
            return 0, self._disk_usage_percent()

        files.sort(key=lambda x: x[1])
        files_to_remove = len(files) - min_keep
        removed = 0
        usage_percent = 100.0

        for filepath, _ in files[:files_to_remove]:
            try:
                os.remove(filepath)
                removed += 1
                print(f"[DiskMonitor] Removed {label} (LRU): {filepath}")

                usage_percent = self._disk_usage_percent()
                if usage_percent < DISK_USAGE_THRESHOLD_PERCENT:
                    return removed, usage_percent
            except OSError as e:
                print(f"[DiskMonitor] Failed to remove {filepath}: {e}")

        return removed, usage_percent

    @staticmethod
    def _disk_usage_percent() -> float:
        disk_usage = shutil.disk_usage(STORAGE_DIR)
        return (disk_usage.used / disk_usage.total) * 100
