"""Centralized storage paths configuration.

The base storage directory can be configured via the WORKER_STORAGE_DIR environment variable.
This allows using instance storage (e.g., NVMe on g6.xlarge EC2 instances) instead of /tmp.

Default: /tmp/qmr-worker
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

# Application root directory (parent of worker/)
APP_DIR = Path(__file__).parent.parent

# Static assets directory (bundled with application)
ASSETS_DIR = APP_DIR / "assets"

# Base storage directory - configurable via environment variable
# Useful for utilizing instance storage on EC2 (e.g., /mnt/nvme/qmr-worker)
STORAGE_DIR = os.getenv("WORKER_STORAGE_DIR", "/tmp/qmr-worker")

# Subdirectory paths
IMAGES_DIR = os.path.join(STORAGE_DIR, "images")
TEMPLATES_DIR = os.path.join(STORAGE_DIR, "templates")
RESULTS_DIR = os.path.join(STORAGE_DIR, "results")
CACHE_DIR = os.path.join(STORAGE_DIR, "cache")
# Debug dumps live outside RESULTS_DIR so the post-job cleanup
# (ScanWorker._cleanup_processed_images) does not erase them.
DEBUG_DIR = os.path.join(STORAGE_DIR, "debug")


def get_image_path(image_id: UUID, extension: str) -> str:
    """Get the path for a downloaded scan image."""
    return os.path.join(IMAGES_DIR, f"{image_id}{extension}")


def get_template_path(template_id: UUID, extension: str) -> str:
    """Get the path for a downloaded template image."""
    return os.path.join(TEMPLATES_DIR, f"{template_id}{extension}")


def get_results_dir(request_id: UUID, job_id: UUID) -> str:
    """Get the results directory for a specific job."""
    return os.path.join(RESULTS_DIR, str(request_id), str(job_id))


def get_result_path(request_id: UUID, job_id: UUID, filename: str) -> str:
    """Get the path for a result file."""
    return os.path.join(RESULTS_DIR, str(request_id), str(job_id), filename)


def get_request_results_dir(request_id: UUID) -> str:
    """Get the results directory for a specific request."""
    return os.path.join(RESULTS_DIR, str(request_id))


def get_debug_dir(request_id: UUID, job_id: UUID) -> str:
    """Per-job debug dump directory."""
    return os.path.join(DEBUG_DIR, str(request_id), str(job_id))


def init_storage_dirs() -> None:
    """Initialize the storage directories."""
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
