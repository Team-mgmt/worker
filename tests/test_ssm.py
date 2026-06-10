"""Tests for worker.ssm module."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

from worker.ssm import (
    IMDS_REGION_URL,
    IMDS_TOKEN_URL,
    get_region_from_imds,
    load_ssm_parameters,
)


class TestGetRegionFromImds:
    async def test_success(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, body="token123")
            m.get(IMDS_REGION_URL, body="us-east-1")
            result = await get_region_from_imds()
            assert result == "us-east-1"

    async def test_token_failure(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, status=500)
            result = await get_region_from_imds()
            assert result is None

    async def test_region_failure(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, body="token123")
            m.get(IMDS_REGION_URL, status=500)
            result = await get_region_from_imds()
            assert result is None

    async def test_timeout(self):
        with aioresponses() as m:
            m.put(IMDS_TOKEN_URL, exception=asyncio.TimeoutError())
            result = await get_region_from_imds()
            assert result is None


class TestLoadSsmParameters:
    async def test_no_parameter_path(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSM_PARAMETER_PATH", None)
            await load_ssm_parameters()
            # Should return without error

    async def test_loads_parameters(self):
        mock_paginator = MagicMock()

        async def mock_paginate(**kwargs):
            yield {
                "Parameters": [
                    {"Name": "/shelfalign/worker/DATABASE_URL", "Value": "postgres://localhost"},
                    {"Name": "/shelfalign/worker/S3_BUCKET_NAME", "Value": "my-bucket"},
                ]
            }

        mock_paginator.paginate = mock_paginate

        mock_ssm = MagicMock()
        mock_ssm.get_paginator = MagicMock(return_value=mock_paginator)

        mock_session = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_ssm)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.region_name = "us-east-1"

        with (
            patch.dict(os.environ, {"SSM_PARAMETER_PATH": "/shelfalign/worker/"}, clear=False),
            patch("worker.ssm.aioboto3.Session", return_value=mock_session),
        ):
            await load_ssm_parameters()
            assert os.environ.get("DATABASE_URL") == "postgres://localhost"
            assert os.environ.get("S3_BUCKET_NAME") == "my-bucket"

    async def test_adds_trailing_slash(self):
        mock_paginator = MagicMock()

        async def mock_paginate(**kwargs):
            yield {"Parameters": []}

        mock_paginator.paginate = mock_paginate

        mock_ssm = MagicMock()
        mock_ssm.get_paginator = MagicMock(return_value=mock_paginator)

        mock_session = MagicMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_ssm)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.region_name = "us-east-1"

        with (
            patch.dict(os.environ, {"SSM_PARAMETER_PATH": "/shelfalign/worker"}, clear=False),
            patch("worker.ssm.aioboto3.Session", return_value=mock_session),
        ):
            await load_ssm_parameters()
