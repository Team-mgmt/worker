"""Disk-backed font downloads from S3.

Fonts live under ``common/fonts/<name>.ttf`` in the assets bucket (same layout
as shelfalign-web's TeacherFontService consumes). The worker only needs to *render*
text on templates for alignment, so we fetch font bytes lazily and cache them
under CACHE_DIR/fonts/.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import botocore.exceptions

from .paths import CACHE_DIR

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

FONTS_SUBDIR = "fonts"
FONTS_S3_PREFIX = "common/fonts/"

# S3 error codes that indicate "no such font"; treated as None so callers can
# fall back to a default instead of raising.
_S3_NOT_FOUND_CODES = {"NoSuchKey", "NoSuchBucket", "404"}

# Font names ultimately come from ``ExamPaperArea.data["fontFamily"]``, which
# admins can edit via the shelfalign-web UI. The string is interpolated into both a
# local filesystem path and an S3 key, so an attacker-controlled value like
# ``"../../etc/passwd"`` would otherwise escape ``CACHE_DIR/fonts`` and let
# the worker read or overwrite arbitrary paths. Restrict to characters that
# actually appear in legitimate font filenames in our assets bucket (see
# ``s3://<env>-shelfalign-assets/common/fonts/``).
_FONT_NAME_RE = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")

# Per-font async lock so concurrent scans don't race on the same download.
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


def _is_safe_font_name(name: str) -> bool:
    """True if ``name`` is safe to interpolate into a local path / S3 key."""
    return bool(_FONT_NAME_RE.fullmatch(name))


def _local_path(name: str) -> Path:
    return Path(CACHE_DIR) / FONTS_SUBDIR / f"{name}.ttf"


async def _lock_for(name: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            _locks[name] = lock
        return lock


async def get_font_bytes(client: S3Client, bucket: str, name: str) -> bytes | None:
    """Return font bytes for ``<name>.ttf``, downloading from S3 on first miss.

    Returns ``None`` when the font does not exist in S3 (404) or when ``name``
    fails the safe-name allowlist (so callers can fall back to a default font).
    Other S3 errors propagate.
    """
    if not _is_safe_font_name(name):
        return None
    local = _local_path(name)
    if local.exists():
        async with aiofiles.open(local, "rb") as f:
            return await f.read()

    lock = await _lock_for(name)
    async with lock:
        if local.exists():
            async with aiofiles.open(local, "rb") as f:
                return await f.read()

        s3_key = f"{FONTS_S3_PREFIX}{name}.ttf"
        try:
            response = await client.get_object(Bucket=bucket, Key=s3_key)
        except botocore.exceptions.ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in _S3_NOT_FOUND_CODES:
                return None
            raise
        data = await response["Body"].read()

        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(f"{local.name}.{os.getpid()}.tmp")
        async with aiofiles.open(tmp, "wb") as f:
            await f.write(data)
        os.replace(tmp, local)
        return data
