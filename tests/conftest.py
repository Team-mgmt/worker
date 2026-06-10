"""Shared fixtures for the test suite."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest


@pytest.fixture
def sample_uuid():
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def sample_uuid2():
    return uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")


@pytest.fixture
def mock_s3_client():
    client = AsyncMock()
    client.get_object = AsyncMock()
    client.put_object = AsyncMock()
    client.copy_object = AsyncMock()
    return client


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    return engine


@pytest.fixture
def sample_rgb_image():
    """A small 100x100 RGB image."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture
def sample_gray_image():
    """A small 100x100 grayscale image."""
    return np.zeros((100, 100), dtype=np.uint8)


@pytest.fixture
def sample_thresh_image():
    """A 100x100 binary threshold image (white background, some black)."""
    img = np.full((100, 100), 255, dtype=np.uint8)
    img[20:40, 20:40] = 0  # Black square
    return img
