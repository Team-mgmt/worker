"""Tests for worker.fonts."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import botocore.exceptions
import pytest

from worker import fonts


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


@pytest.fixture(autouse=True)
def _clear_lock_state():
    """Per-name async locks persist on the module; clear between tests."""
    fonts._locks.clear()
    yield
    fonts._locks.clear()


async def test_returns_none_on_404():
    error = botocore.exceptions.ClientError(
        error_response={"Error": {"Code": "NoSuchKey"}}, operation_name="GetObject"
    )
    client = AsyncMock()
    client.get_object.side_effect = error

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            result = await fonts.get_font_bytes(client, "any-bucket", "MissingFont-Regular")
    assert result is None


async def test_propagates_other_client_errors():
    error = botocore.exceptions.ClientError(
        error_response={"Error": {"Code": "AccessDenied"}}, operation_name="GetObject"
    )
    client = AsyncMock()
    client.get_object.side_effect = error

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            with pytest.raises(botocore.exceptions.ClientError):
                await fonts.get_font_bytes(client, "any-bucket", "AnyFont-Regular")


async def test_downloads_from_s3_on_miss_and_caches():
    payload = b"\x00\x01\x02fontbytes"
    client = AsyncMock()
    client.get_object.return_value = {"Body": _FakeBody(payload)}

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            first = await fonts.get_font_bytes(client, "bucket", "Pretendard-Regular")
            assert first == payload
            # Local cache hit on second call — no second S3 download.
            client.get_object.reset_mock()
            second = await fonts.get_font_bytes(client, "bucket", "Pretendard-Regular")
            assert second == payload
            client.get_object.assert_not_called()
            assert (Path(tmpdir) / "fonts" / "Pretendard-Regular.ttf").exists()


async def test_s3_key_uses_common_fonts_prefix():
    """The worker reads from the same prefix qmr-web's TeacherFontService writes to."""
    payload = b"fontbytes"
    client = AsyncMock()
    client.get_object.return_value = {"Body": _FakeBody(payload)}

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            await fonts.get_font_bytes(client, "the-bucket", "Pretendard-Bold")

    _, call_kwargs = client.get_object.call_args
    assert call_kwargs["Bucket"] == "the-bucket"
    assert call_kwargs["Key"] == "common/fonts/Pretendard-Bold.ttf"


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "../../etc/passwd",
        "..",
        "/abs/path",
        "subdir/Font",
        "Font\\Name",
        "Font.With.Dots",  # extension is added by us; dots in stem rejected too
        "Font Name",  # whitespace
        "Font$Name",
        "한글-Font",  # not in our S3 inventory; rejected
        "x" * 129,  # over length cap
    ],
)
async def test_unsafe_font_name_returns_none_without_s3_or_disk_io(bad_name):
    """Path-traversal / unsafe names must short-circuit before any S3 GET or
    local file open: ``fontFamily`` is admin-editable template metadata."""
    client = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            result = await fonts.get_font_bytes(client, "the-bucket", bad_name)
            assert result is None
            client.get_object.assert_not_called()
            # Nothing should have been written under CACHE_DIR/fonts.
            fonts_dir = Path(tmpdir) / "fonts"
            if fonts_dir.exists():
                assert list(fonts_dir.iterdir()) == []


@pytest.mark.parametrize(
    "good_name",
    [
        "Pretendard-Regular",
        "Pretendard-Bold",
        "HakgyoansimBareondotumB",
        "ChosunCentennial_ttf",
        "Font-1",
    ],
)
async def test_safe_font_names_are_accepted(good_name):
    """Names matching the legitimate font-name shape pass through to S3."""
    payload = b"x"
    client = AsyncMock()
    client.get_object.return_value = {"Body": _FakeBody(payload)}

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(fonts, "CACHE_DIR", tmpdir):
            result = await fonts.get_font_bytes(client, "bucket", good_name)
    assert result == payload
