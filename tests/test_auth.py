"""Tests for worker.auth module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.auth import create_async_creator


class TestCreateAsyncCreator:
    async def test_returns_callable(self):
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"

        creator = await create_async_creator(
            "postgresql://user:pass@host:5432/dbname",
            region="us-east-1",
            session=mock_session,
        )
        assert callable(creator)

    async def test_raises_on_invalid_url(self):
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"

        with pytest.raises(ValueError, match="host"):
            await create_async_creator(
                "postgresql://",
                region="us-east-1",
                session=mock_session,
            )

    async def test_uses_default_port(self):
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"

        creator = await create_async_creator(
            "postgresql://user@host/dbname",
            region="us-east-1",
            session=mock_session,
        )
        assert callable(creator)

    async def test_uses_imds_region_fallback(self):
        mock_session = MagicMock()
        mock_session.region_name = None

        with patch("worker.auth.get_region_from_imds", AsyncMock(return_value="ap-northeast-2")):
            creator = await create_async_creator(
                "postgresql://user@host/dbname",
                session=mock_session,
            )
            assert callable(creator)

    async def test_uses_bastion_region_when_aws_region_unset(self):
        mock_session = MagicMock()
        mock_session.region_name = None

        # Stub session.client("rds", region_name=...) so we can capture the
        # region passed to the RDS client and to generate_db_auth_token.
        rds_client = MagicMock()
        rds_client.generate_db_auth_token = AsyncMock(return_value="iam-token")
        rds_cm = MagicMock()
        rds_cm.__aenter__ = AsyncMock(return_value=rds_client)
        rds_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.client = MagicMock(return_value=rds_cm)

        bastion = MagicMock()
        bastion.config.region = "eu-west-1"
        bastion.lease.bastion_ip = "10.0.0.1"
        bastion.lease.bastion_port = 15432

        with (
            patch("worker.auth.get_region_from_imds", AsyncMock(return_value=None)),
            patch("worker.auth.psycopg.AsyncConnection.connect", AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            creator = await create_async_creator(
                "postgresql://user@host/dbname",
                session=mock_session,
                bastion=bastion,
            )
            await creator()

        mock_session.client.assert_called_once_with("rds", region_name="eu-west-1")
        rds_client.generate_db_auth_token.assert_awaited_once()
        assert rds_client.generate_db_auth_token.await_args.kwargs["Region"] == "eu-west-1"
        mock_connect.assert_awaited_once()
