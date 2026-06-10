"""Bastion lease broker client.

Routes PostgreSQL connections through a lease-broker bastion so that Runpod
workers can reach a private-subnet RDS instance without public RDS exposure.

Activated by ``BASTION_ENABLED=true``. When active:

1. :class:`BastionSession` opens a lease by calling the broker with a presigned
   ``sts:GetCallerIdentity`` URL as its identity proof (aws-iam-authenticator
   pattern). The broker replays the URL to STS to authenticate the caller and
   then authorizes against its allowlist.
2. A background task refreshes the lease every ``keepalive_interval_seconds``.
3. Callers build a PostgreSQL connection using ``host=<rds-endpoint>``,
   ``hostaddr=<bastion_ip>``, ``port=<leased_port>`` so TLS still terminates
   on RDS and ``sslmode=verify-full`` remains valid.
4. Lease is closed on session exit.

Request auth protocol:

* The bastion request body carries ``nonce`` (uuid) alongside the usual fields.
* The worker presigns ``GET https://sts.<region>.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15``
  with SigV4 query-string signing and a custom header
  ``x-bastion-request-nonce`` included in the signed-headers list whose value
  is the same nonce as in the body.
* The presigned URL is sent to the broker in the
  ``X-Bastion-Sts-Presigned-Url`` header.
* The broker reads ``body.nonce``, issues ``GET`` to the presigned URL with
  ``x-bastion-request-nonce: <body.nonce>``. STS validates the signature
  (which proves the caller signed *this* nonce) and returns the caller's ARN,
  AccountId and UserId.

This cryptographically binds the identity check to the specific lease request
without the broker needing the caller's secret key.

See spec sections 8, 9, 10, 13.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aioboto3
import httpx
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from worker.ssm import get_region_from_imds

logger = logging.getLogger(__name__)


DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_KEEPALIVE_INTERVAL_SECONDS = 20
DEFAULT_KEEPALIVE_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_KEEPALIVE_MAX_RETRIES = 3
DEFAULT_STS_PRESIGNED_TTL_SECONDS = 60

STS_GET_CALLER_IDENTITY_QUERY = "Action=GetCallerIdentity&Version=2011-06-15"
BASTION_PRESIGNED_URL_HEADER = "X-Bastion-Sts-Presigned-Url"
BASTION_REQUEST_NONCE_HEADER = "x-bastion-request-nonce"


class BastionError(Exception):
    """Base bastion broker error."""


class BastionConfigError(BastionError):
    """Raised when required bastion configuration is missing or invalid."""


class BrokerHTTPError(BastionError):
    """Broker returned a non-2xx HTTP response."""

    def __init__(self, status_code: int, code: str, message: str, retryable: bool):
        super().__init__(f"{code}: {message} (HTTP {status_code})")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


class UnauthorizedError(BrokerHTTPError):
    """Caller or DB target not authorized by broker policy."""


class LeaseNotFoundError(BrokerHTTPError):
    """Lease id does not exist or is not owned by caller."""


class LeaseExpiredError(BrokerHTTPError):
    """Lease has expired on the broker."""


class PortPoolExhaustedError(BrokerHTTPError):
    """Broker has no free data-plane ports."""


# Broker error codes per spec §20.
_ERROR_CODE_MAP: dict[str, type[BrokerHTTPError]] = {
    "INVALID_SIGNATURE": UnauthorizedError,
    "REQUEST_EXPIRED": UnauthorizedError,
    "REPLAY_DETECTED": UnauthorizedError,
    "UNAUTHORIZED_CALLER": UnauthorizedError,
    "UNAUTHORIZED_DB_TARGET": UnauthorizedError,
    "PORT_POOL_EXHAUSTED": PortPoolExhaustedError,
    "LEASE_NOT_FOUND": LeaseNotFoundError,
    "LEASE_NOT_OWNER": LeaseNotFoundError,
    "LEASE_EXPIRED": LeaseExpiredError,
}


@dataclass(frozen=True)
class BastionConfig:
    """Static configuration for a bastion session."""

    broker_url: str
    rds_endpoint: str
    rds_port: int
    db_user: str
    region: str
    sts_endpoint_url: Optional[str] = None
    sts_presigned_ttl_seconds: int = DEFAULT_STS_PRESIGNED_TTL_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    keepalive_interval_seconds: int = DEFAULT_KEEPALIVE_INTERVAL_SECONDS

    def resolved_sts_endpoint_url(self) -> str:
        return self.sts_endpoint_url or f"https://sts.{self.region}.amazonaws.com/"

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv("BASTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    async def from_env(
        cls,
        *,
        rds_endpoint: str,
        rds_port: int,
        db_user: str,
        region: Optional[str] = None,
    ) -> "BastionConfig":
        broker_url = os.getenv("BASTION_BROKER_URL")
        if not broker_url:
            raise BastionConfigError("BASTION_BROKER_URL is required when BASTION_ENABLED=true")

        resolved_region = (
            region
            or os.getenv("BASTION_REGION")
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or await get_region_from_imds()
        )
        if not resolved_region:
            raise BastionConfigError("Region could not be resolved (set BASTION_REGION or AWS_REGION)")

        return cls(
            broker_url=broker_url.rstrip("/"),
            rds_endpoint=rds_endpoint,
            rds_port=rds_port,
            db_user=db_user,
            region=resolved_region,
            sts_endpoint_url=os.getenv("BASTION_STS_ENDPOINT_URL") or None,
            sts_presigned_ttl_seconds=int(os.getenv("BASTION_STS_PRESIGNED_TTL_SECONDS", DEFAULT_STS_PRESIGNED_TTL_SECONDS)),
            request_timeout_seconds=float(os.getenv("BASTION_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS)),
            keepalive_interval_seconds=int(os.getenv("BASTION_KEEPALIVE_INTERVAL_SECONDS", DEFAULT_KEEPALIVE_INTERVAL_SECONDS)),
        )


@dataclass(frozen=True)
class Lease:
    """Lease metadata returned by the broker (spec §9.1, §10.1 response)."""

    lease_id: str
    bastion_ip: str
    bastion_port: int
    db_endpoint: str
    db_port: int
    expires_at: datetime
    # None means the broker did not specify; the caller should fall back to its
    # configured default (BastionConfig.keepalive_interval_seconds).
    keepalive_interval_seconds: Optional[int]
    grace_period_seconds: int

    @classmethod
    def from_response(cls, body: dict[str, Any]) -> "Lease":
        try:
            raw_interval = body.get("keepalive_interval_seconds")
            return cls(
                lease_id=body["lease_id"],
                bastion_ip=body["bastion_ip"],
                bastion_port=int(body["bastion_port"]),
                db_endpoint=body["db_endpoint"],
                db_port=int(body["db_port"]),
                expires_at=_parse_iso8601(body["expires_at"]),
                keepalive_interval_seconds=int(raw_interval) if raw_interval is not None else None,
                grace_period_seconds=int(body.get("grace_period_seconds", 30)),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise BastionError(f"Malformed lease response: {e}") from e

    def with_extended_expiry(self, expires_at: datetime) -> "Lease":
        return Lease(
            lease_id=self.lease_id,
            bastion_ip=self.bastion_ip,
            bastion_port=self.bastion_port,
            db_endpoint=self.db_endpoint,
            db_port=self.db_port,
            expires_at=expires_at,
            keepalive_interval_seconds=self.keepalive_interval_seconds,
            grace_period_seconds=self.grace_period_seconds,
        )


class LeaseClient:
    """Async client for the bastion broker control-plane API.

    Each request includes a presigned ``sts:GetCallerIdentity`` URL in the
    ``X-Bastion-Sts-Presigned-Url`` header. The presigned URL is bound to the
    body's ``nonce`` via a signed ``x-bastion-request-nonce`` custom header.
    The broker replays the URL to STS with that nonce value to authenticate
    the caller (aws-iam-authenticator pattern).
    """

    def __init__(
        self,
        config: BastionConfig,
        *,
        session: Optional[aioboto3.Session] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._config = config
        self._session = session if session is not None else aioboto3.Session()
        self._http_client = http_client
        self._owned_http_client = http_client is None

    async def __aenter__(self) -> "LeaseClient":
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._config.request_timeout_seconds)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._owned_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def open(self, *, client_hint: Optional[dict[str, str]] = None) -> Lease:
        body: dict[str, Any] = {
            "nonce": str(uuid.uuid4()),
            "lease_request_id": str(uuid.uuid4()),
            "requested_at": _utcnow_iso(),
            "db_endpoint": self._config.rds_endpoint,
            "db_port": self._config.rds_port,
            "db_user": self._config.db_user,
        }
        if client_hint:
            body["client_hint"] = client_hint
        response = await self._post("/v1/lease/open", body)
        return Lease.from_response(response)

    async def keepalive(self, lease: Lease) -> Lease:
        body = {
            "lease_id": lease.lease_id,
            "nonce": str(uuid.uuid4()),
            "requested_at": _utcnow_iso(),
        }
        response = await self._post("/v1/lease/keepalive", body)
        # Malformed 200 payloads (missing / invalid expires_at, e.g. broker
        # version skew) must surface as BastionError so the keepalive loop's
        # terminal handler can trigger shutdown instead of the task dying
        # with an unhandled KeyError/ValueError.
        try:
            return lease.with_extended_expiry(_parse_iso8601(response["expires_at"]))
        except (KeyError, TypeError, ValueError) as e:
            raise BastionError(f"Malformed keepalive response: {e}") from e

    async def close(self, lease: Lease) -> None:
        body = {
            "lease_id": lease.lease_id,
            "nonce": str(uuid.uuid4()),
            "requested_at": _utcnow_iso(),
        }
        await self._post("/v1/lease/close", body)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._http_client is None:
            raise BastionError("LeaseClient must be used as an async context manager")

        url = f"{self._config.broker_url}{path}"
        payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        presigned_url = await self._presign_sts_get_caller_identity(body["nonce"])
        headers = {
            "Content-Type": "application/json",
            BASTION_PRESIGNED_URL_HEADER: presigned_url,
        }
        response = await self._http_client.post(url, content=payload, headers=headers)
        return _parse_response(response)

    async def _presign_sts_get_caller_identity(self, nonce: str) -> str:
        """Return a presigned STS GetCallerIdentity URL bound to ``nonce``.

        The ``x-bastion-request-nonce`` header is part of the signed-headers
        list; STS will accept the replay only when the broker passes that
        same header value (i.e. the request body's nonce) when calling STS.
        """
        # aioboto3's type stubs mark these synchronous but they are awaitables at runtime.
        credentials = await self._session.get_credentials()  # type: ignore[misc]
        if credentials is None:
            raise BastionConfigError("No AWS credentials available for STS presigning")
        frozen = await credentials.get_frozen_credentials()  # type: ignore[misc]

        base_url = self._config.resolved_sts_endpoint_url().rstrip("/") + "/"
        url = f"{base_url}?{STS_GET_CALLER_IDENTITY_QUERY}"
        aws_request = AWSRequest(
            method="GET",
            url=url,
            headers={BASTION_REQUEST_NONCE_HEADER: nonce},
        )
        signer = SigV4QueryAuth(frozen, "sts", self._config.region, expires=self._config.sts_presigned_ttl_seconds)
        signer.add_auth(aws_request)
        if aws_request.url is None:
            raise BastionError("SigV4QueryAuth did not produce a URL")
        return aws_request.url


class BastionSession:
    """Owns one active lease and the background keepalive task.

    Use as an async context manager. On ``__aenter__`` it acquires a lease; the
    keepalive loop runs until ``__aexit__``, which closes the lease.
    """

    def __init__(
        self,
        config: BastionConfig,
        *,
        session: Optional[aioboto3.Session] = None,
        client: Optional[LeaseClient] = None,
        client_hint: Optional[dict[str, str]] = None,
    ) -> None:
        self._config = config
        self._aio_session = session if session is not None else aioboto3.Session()
        self._client_hint = client_hint
        self._client = client
        self._owns_client = client is None
        self._lease: Optional[Lease] = None
        self._keepalive_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._keepalive_lost = asyncio.Event()

    @property
    def lease(self) -> Lease:
        if self._lease is None:
            raise BastionError("BastionSession is not active (enter the context first)")
        return self._lease

    @property
    def config(self) -> BastionConfig:
        return self._config

    @property
    def keepalive_lost(self) -> asyncio.Event:
        """Set when keepalive permanently fails; callers should trigger shutdown."""
        return self._keepalive_lost

    async def __aenter__(self) -> "BastionSession":
        if self._client is None:
            self._client = LeaseClient(self._config, session=self._aio_session)
            await self._client.__aenter__()
        self._lease = await self._client.open(client_hint=self._client_hint)
        logger.info(
            "bastion.lease.opened",
            extra={
                "lease_id": self._lease.lease_id,
                "bastion_ip": self._lease.bastion_ip,
                "bastion_port": self._lease.bastion_port,
                "expires_at": self._lease.expires_at.isoformat(),
            },
        )
        self._keepalive_task = asyncio.create_task(self._run_keepalive(), name="bastion-keepalive")
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except (asyncio.CancelledError, Exception):
                pass
            self._keepalive_task = None

        if self._client is not None and self._lease is not None:
            try:
                await asyncio.wait_for(self._client.close(self._lease), timeout=self._config.request_timeout_seconds)
                logger.info("bastion.lease.closed", extra={"lease_id": self._lease.lease_id})
            except Exception as e:
                logger.warning("bastion.lease.close_failed", extra={"lease_id": self._lease.lease_id, "error": str(e)})

        if self._owns_client and self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
        self._client = None
        self._lease = None

    async def _run_keepalive(self) -> None:
        assert self._client is not None
        assert self._lease is not None
        interval = max(1, self._lease.keepalive_interval_seconds or self._config.keepalive_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                async with self._lock:
                    updated = await self._keepalive_with_retry()
                    self._lease = updated
                logger.debug("bastion.lease.keepalive_ok", extra={"lease_id": updated.lease_id, "expires_at": updated.expires_at.isoformat()})
            except asyncio.CancelledError:
                raise
            except BastionError as e:
                logger.error("bastion.lease.keepalive_lost", extra={"lease_id": self._lease.lease_id, "error": str(e)})
                # Lease is permanently lost (retries exhausted, or LeaseNotFound/
                # LeaseExpired). Signal callers so the worker can shut down and be
                # restarted with a fresh lease instead of running with a stale one.
                self._keepalive_lost.set()
                return

    async def _keepalive_with_retry(self) -> Lease:
        assert self._client is not None
        assert self._lease is not None
        last_error: Optional[Exception] = None
        for attempt in range(DEFAULT_KEEPALIVE_MAX_RETRIES):
            try:
                return await self._client.keepalive(self._lease)
            except LeaseNotFoundError as e:
                raise e
            except LeaseExpiredError as e:
                raise e
            except (BrokerHTTPError, httpx.HTTPError) as e:
                last_error = e
                await asyncio.sleep(DEFAULT_KEEPALIVE_RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise BastionError(f"Keepalive exhausted retries: {last_error}")


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso8601(value: str) -> datetime:
    # Accept Z suffix (RFC 3339) used throughout the spec examples.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_success:
        if not isinstance(body, dict):
            raise BastionError(f"Unexpected broker response: {body!r}")
        return body

    # Spec §20 error envelope
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = str(err.get("code") or "BROKER_INTERNAL_ERROR")
    message = str(err.get("message") or response.text or "broker error")
    retryable = bool(err.get("retryable", False))
    exc_cls = _ERROR_CODE_MAP.get(code, BrokerHTTPError)
    raise exc_cls(response.status_code, code, message, retryable)


