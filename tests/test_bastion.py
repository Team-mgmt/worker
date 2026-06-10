"""Tests for worker.bastion."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from worker.bastion import (
    BASTION_PRESIGNED_URL_HEADER,
    BASTION_REQUEST_NONCE_HEADER,
    BastionConfig,
    BastionError,
    BastionSession,
    BrokerHTTPError,
    Lease,
    LeaseClient,
    LeaseNotFoundError,
    PortPoolExhaustedError,
    UnauthorizedError,
)

BROKER_URL = "https://bastion-api.example.com"
RDS_ENDPOINT = "mydb.abc123.ap-northeast-2.rds.amazonaws.com"
BASTION_IP = "203.0.113.10"
BASTION_PORT = 18443


@pytest.fixture
def fake_aws_credentials(monkeypatch):
    """Inject deterministic AWS credentials for SigV4 signing."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")


@pytest.fixture
def config() -> BastionConfig:
    return BastionConfig(
        broker_url=BROKER_URL,
        rds_endpoint=RDS_ENDPOINT,
        rds_port=5432,
        db_user="app_iam_user",
        region="ap-northeast-2",
        keepalive_interval_seconds=1,
    )


def _lease_response(expires_in_seconds: int = 120) -> dict[str, Any]:
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in_seconds)
    return {
        "lease_id": "00000000-0000-0000-0000-000000000001",
        "bastion_ip": BASTION_IP,
        "bastion_port": BASTION_PORT,
        "db_endpoint": RDS_ENDPOINT,
        "db_port": 5432,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keepalive_interval_seconds": 20,
        "grace_period_seconds": 30,
    }


class TestBastionConfig:
    def test_is_enabled_truthy_values(self, monkeypatch):
        for value in ["true", "TRUE", "1", "yes", "on"]:
            monkeypatch.setenv("BASTION_ENABLED", value)
            assert BastionConfig.is_enabled() is True

    def test_is_enabled_falsy(self, monkeypatch):
        monkeypatch.setenv("BASTION_ENABLED", "false")
        assert BastionConfig.is_enabled() is False
        monkeypatch.delenv("BASTION_ENABLED", raising=False)
        assert BastionConfig.is_enabled() is False

    async def test_from_env_requires_broker_url(self, monkeypatch):
        monkeypatch.delenv("BASTION_BROKER_URL", raising=False)
        with pytest.raises(Exception, match="BASTION_BROKER_URL"):
            await BastionConfig.from_env(
                rds_endpoint=RDS_ENDPOINT,
                rds_port=5432,
                db_user="app",
                region="ap-northeast-2",
            )

    async def test_from_env_trims_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("BASTION_BROKER_URL", "https://broker.example.com/")
        cfg = await BastionConfig.from_env(
            rds_endpoint=RDS_ENDPOINT,
            rds_port=5432,
            db_user="app",
            region="ap-northeast-2",
        )
        assert cfg.broker_url == "https://broker.example.com"

    async def test_from_env_falls_back_to_aws_default_region(self, monkeypatch):
        """Non-EC2 hosts that only set AWS_DEFAULT_REGION (not AWS_REGION) should
        still resolve a region via the aioboto3 session chain."""
        monkeypatch.setenv("BASTION_BROKER_URL", "https://broker.example.com")
        monkeypatch.delenv("BASTION_REGION", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")

        with patch("worker.bastion.get_region_from_imds", AsyncMock(return_value=None)):
            cfg = await BastionConfig.from_env(
                rds_endpoint=RDS_ENDPOINT,
                rds_port=5432,
                db_user="app",
            )

        assert cfg.region == "eu-west-1"


class TestLeaseParsing:
    def test_from_response_happy_path(self):
        lease = Lease.from_response(_lease_response())
        assert lease.lease_id == "00000000-0000-0000-0000-000000000001"
        assert lease.bastion_ip == BASTION_IP
        assert lease.bastion_port == BASTION_PORT
        assert lease.expires_at.tzinfo is not None

    def test_from_response_missing_field(self):
        bad = _lease_response()
        del bad["bastion_port"]
        with pytest.raises(BastionError):
            Lease.from_response(bad)

    def test_from_response_omitted_keepalive_interval_falls_back_to_config(self):
        """When the broker omits keepalive_interval_seconds, store None so the
        session falls back to BastionConfig.keepalive_interval_seconds instead
        of the library default (20s). Otherwise operator-tuned intervals via
        BASTION_KEEPALIVE_INTERVAL_SECONDS are silently ignored."""
        body = _lease_response()
        del body["keepalive_interval_seconds"]
        lease = Lease.from_response(body)
        assert lease.keepalive_interval_seconds is None


class TestLeaseClient:
    async def test_open_sends_presigned_sts_sidecar(self, config, fake_aws_credentials):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_lease_response())

        with respx.mock(assert_all_called=True) as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(side_effect=handler)
            async with LeaseClient(config) as client:
                lease = await client.open(client_hint={"worker_id": "w-1"})

        assert lease.bastion_port == BASTION_PORT

        # Main POST carries no Authorization; identity is in the sidecar URL.
        assert "authorization" not in captured["headers"]
        presigned = captured["headers"][BASTION_PRESIGNED_URL_HEADER.lower()]
        parsed = urlparse(presigned)
        assert parsed.scheme == "https"
        assert parsed.hostname == f"sts.{config.region}.amazonaws.com"
        qs = parse_qs(parsed.query)
        assert qs["Action"] == ["GetCallerIdentity"]
        assert qs["Version"] == ["2011-06-15"]
        assert qs["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        assert qs["X-Amz-Expires"] == [str(config.sts_presigned_ttl_seconds)]
        # The custom nonce header must be part of the signed-headers set so the
        # broker's replay with that value is cryptographically bound to this body.
        signed_headers = qs["X-Amz-SignedHeaders"][0].split(";")
        assert BASTION_REQUEST_NONCE_HEADER in signed_headers
        assert "host" in signed_headers
        assert f"/{config.region}/sts/aws4_request" in qs["X-Amz-Credential"][0]

        body = captured["body"]
        assert body["db_endpoint"] == RDS_ENDPOINT
        assert body["db_user"] == "app_iam_user"
        assert body["db_port"] == 5432
        assert "nonce" in body and "lease_request_id" in body and "requested_at" in body
        assert body["client_hint"] == {"worker_id": "w-1"}

    async def test_presigned_nonce_matches_body_nonce(self, config, fake_aws_credentials):
        """The broker replays the presigned URL with body.nonce; the signature
        only verifies if the signed nonce header value matches the body nonce.

        We can't directly read the signed header value from a presigned URL
        (SigV4 query-string signing omits header values), but we can prove the
        binding by re-signing with a different nonce and confirming the
        signature differs."""
        captured_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(request.headers[BASTION_PRESIGNED_URL_HEADER.lower()])
            return httpx.Response(200, json=_lease_response())

        with respx.mock(assert_all_called=False) as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(side_effect=handler)
            async with LeaseClient(config) as client:
                await client.open()
                await client.open()

        sig_a = parse_qs(urlparse(captured_urls[0]).query)["X-Amz-Signature"][0]
        sig_b = parse_qs(urlparse(captured_urls[1]).query)["X-Amz-Signature"][0]
        # Different nonces → different canonical requests → different signatures.
        assert sig_a != sig_b

    async def test_keepalive_extends_expiry(self, config, fake_aws_credentials):
        lease = Lease.from_response(_lease_response(expires_in_seconds=60))
        new_expiry = datetime.now(tz=timezone.utc) + timedelta(seconds=300)

        with respx.mock(assert_all_called=True) as router:
            router.post(f"{BROKER_URL}/v1/lease/keepalive").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "lease_id": lease.lease_id,
                        "expires_at": new_expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "state": "active",
                    },
                )
            )
            async with LeaseClient(config) as client:
                updated = await client.keepalive(lease)

        assert updated.lease_id == lease.lease_id
        # New expiry within 5s of expected
        assert abs((updated.expires_at - new_expiry).total_seconds()) < 5

    async def test_keepalive_raises_bastion_error_on_malformed_response(self, config, fake_aws_credentials):
        """Malformed 200 keepalive payloads (missing / invalid expires_at,
        e.g. broker version skew) must surface as BastionError. Otherwise
        KeyError/ValueError escapes the keepalive loop's terminal handler
        and the worker keeps running with a lease nobody is refreshing."""
        lease = Lease.from_response(_lease_response())

        with respx.mock(assert_all_called=True) as router:
            router.post(f"{BROKER_URL}/v1/lease/keepalive").mock(
                return_value=httpx.Response(200, json={"lease_id": lease.lease_id, "state": "active"})
            )
            async with LeaseClient(config) as client:
                with pytest.raises(BastionError, match="Malformed keepalive response"):
                    await client.keepalive(lease)

    async def test_close_succeeds(self, config, fake_aws_credentials):
        lease = Lease.from_response(_lease_response())

        with respx.mock(assert_all_called=True) as router:
            router.post(f"{BROKER_URL}/v1/lease/close").mock(
                return_value=httpx.Response(200, json={"lease_id": lease.lease_id, "state": "closed"})
            )
            async with LeaseClient(config) as client:
                await client.close(lease)

    async def test_maps_unauthorized_caller(self, config, fake_aws_credentials):
        with respx.mock() as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(
                return_value=httpx.Response(
                    403,
                    json={"error": {"code": "UNAUTHORIZED_CALLER", "message": "not allowed", "retryable": False}},
                )
            )
            async with LeaseClient(config) as client:
                with pytest.raises(UnauthorizedError) as exc:
                    await client.open()
        assert exc.value.code == "UNAUTHORIZED_CALLER"
        assert exc.value.status_code == 403

    async def test_maps_lease_not_found(self, config, fake_aws_credentials):
        lease = Lease.from_response(_lease_response())
        with respx.mock() as router:
            router.post(f"{BROKER_URL}/v1/lease/keepalive").mock(
                return_value=httpx.Response(
                    404,
                    json={"error": {"code": "LEASE_NOT_FOUND", "message": "gone", "retryable": False}},
                )
            )
            async with LeaseClient(config) as client:
                with pytest.raises(LeaseNotFoundError):
                    await client.keepalive(lease)

    async def test_maps_port_pool_exhausted(self, config, fake_aws_credentials):
        with respx.mock() as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(
                return_value=httpx.Response(
                    503,
                    json={"error": {"code": "PORT_POOL_EXHAUSTED", "message": "full", "retryable": True}},
                )
            )
            async with LeaseClient(config) as client:
                with pytest.raises(PortPoolExhaustedError) as exc:
                    await client.open()
        assert exc.value.retryable is True

    async def test_unknown_error_code_falls_back(self, config, fake_aws_credentials):
        with respx.mock() as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(
                return_value=httpx.Response(
                    500,
                    json={"error": {"code": "SOMETHING_ODD", "message": "boom"}},
                )
            )
            async with LeaseClient(config) as client:
                with pytest.raises(BrokerHTTPError) as exc:
                    await client.open()
        assert exc.value.code == "SOMETHING_ODD"
        assert exc.value.status_code == 500


class TestBastionSession:
    async def test_lifecycle_opens_and_closes(self, config, fake_aws_credentials):
        open_response = _lease_response()

        with respx.mock(assert_all_called=True) as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(return_value=httpx.Response(200, json=open_response))
            router.post(f"{BROKER_URL}/v1/lease/close").mock(
                return_value=httpx.Response(200, json={"lease_id": open_response["lease_id"], "state": "closed"})
            )

            async with BastionSession(config) as session:
                assert session.lease.bastion_ip == BASTION_IP
                # lease property works while in context
                assert session.lease.lease_id == open_response["lease_id"]

    async def test_keepalive_loop_fires(self, config, fake_aws_credentials, monkeypatch):
        # Speed up the loop by forcing a 0.05s interval.
        open_body = _lease_response()
        open_body["keepalive_interval_seconds"] = 1  # server suggests 1s

        call_count = {"keepalive": 0}

        def keepalive_handler(request: httpx.Request) -> httpx.Response:
            call_count["keepalive"] += 1
            new_expiry = datetime.now(tz=timezone.utc) + timedelta(seconds=120)
            return httpx.Response(
                200,
                json={
                    "lease_id": open_body["lease_id"],
                    "expires_at": new_expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "state": "active",
                },
            )

        with respx.mock(assert_all_called=False) as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(return_value=httpx.Response(200, json=open_body))
            router.post(f"{BROKER_URL}/v1/lease/keepalive").mock(side_effect=keepalive_handler)
            router.post(f"{BROKER_URL}/v1/lease/close").mock(
                return_value=httpx.Response(200, json={"lease_id": open_body["lease_id"], "state": "closed"})
            )

            async with BastionSession(config):
                # BastionSession uses the lease's keepalive_interval_seconds (1s); wait past one tick.
                await asyncio.sleep(1.2)

        assert call_count["keepalive"] >= 1

    async def test_lease_property_raises_outside_context(self, config):
        session = BastionSession(config)
        with pytest.raises(BastionError):
            _ = session.lease

    async def test_keepalive_lost_event_set_on_terminal_failure(self, config, fake_aws_credentials):
        """When keepalive permanently fails, the session surfaces it via
        ``keepalive_lost`` so the worker can trigger graceful shutdown instead
        of running with a stale lease."""
        open_body = _lease_response()
        open_body["keepalive_interval_seconds"] = 1

        with respx.mock(assert_all_called=False) as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(return_value=httpx.Response(200, json=open_body))
            # LEASE_EXPIRED is a terminal broker state; _keepalive_with_retry
            # re-raises it immediately without retrying.
            router.post(f"{BROKER_URL}/v1/lease/keepalive").mock(
                return_value=httpx.Response(
                    410,
                    json={"error": {"code": "LEASE_EXPIRED", "message": "gone", "retryable": False}},
                )
            )
            router.post(f"{BROKER_URL}/v1/lease/close").mock(
                return_value=httpx.Response(200, json={"lease_id": open_body["lease_id"], "state": "closed"})
            )

            async with BastionSession(config) as session:
                # keepalive loop uses the lease's interval (1s); wait past the first tick.
                await asyncio.wait_for(session.keepalive_lost.wait(), timeout=3.0)
                assert session.keepalive_lost.is_set()

    async def test_open_failure_propagates(self, config, fake_aws_credentials):
        with respx.mock() as router:
            router.post(f"{BROKER_URL}/v1/lease/open").mock(
                return_value=httpx.Response(
                    403,
                    json={"error": {"code": "UNAUTHORIZED_CALLER", "message": "nope", "retryable": False}},
                )
            )
            with pytest.raises(UnauthorizedError):
                async with BastionSession(config):
                    pass


class TestCreateAsyncCreatorWithBastion:
    async def test_passes_hostaddr_and_leased_port_to_psycopg(self, fake_aws_credentials):
        from worker.auth import create_async_creator

        # Build a bastion session with a lease, but stub out psycopg/rds for the creator invocation.
        lease = Lease.from_response(_lease_response())

        class FakeSession:
            lease = None

        fake = FakeSession()
        fake.lease = lease  # type: ignore[assignment]

        with patch("worker.auth.psycopg.AsyncConnection.connect") as mock_connect, patch(
            "worker.auth.aioboto3.Session"
        ) as mock_aio:
            # rds.generate_db_auth_token returns a fixed token
            class Client:
                async def generate_db_auth_token(self, **kwargs):
                    return "iam-token"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return None

            class Sess:
                region_name = "ap-northeast-2"

                def client(self, *_a, **_k):
                    return Client()

            mock_aio.return_value = Sess()
            mock_connect.return_value = object()

            creator = await create_async_creator(
                f"postgresql://app_iam_user@{RDS_ENDPOINT}:5432/appdb",
                region="ap-northeast-2",
                bastion=fake,  # type: ignore[arg-type]
            )
            await creator()

        kwargs = mock_connect.call_args.kwargs
        assert kwargs["host"] == RDS_ENDPOINT
        assert kwargs["hostaddr"] == lease.bastion_ip
        assert kwargs["port"] == lease.bastion_port
        assert kwargs["sslmode"] == "verify-full"
        assert kwargs["password"] == "iam-token"
