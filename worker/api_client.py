"""API client for backend communication with worker authentication."""

from __future__ import annotations

import os
import time
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


# JWT token validity duration (5 minutes)
JWT_EXPIRY_SECONDS = 300


def generate_es512_key_pair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """Generate an ES512 (ECDSA with P-521 curve) key pair.

    Returns:
        Tuple of (private_key, public_key_pem)
        - private_key: The private key object for signing
        - public_key_pem: PEM-encoded public key string for storage
    """
    private_key = ec.generate_private_key(ec.SECP521R1())
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, public_key_pem


class WorkerAPIClient:
    """Client for authenticated API calls to the backend.

    Authentication uses ES512-signed JWTs. The worker ID is included
    in the JWT protected header as the 'iss' (issuer) claim.
    """

    def __init__(
        self,
        api_base_url: str,
        worker_id: UUID | None = None,
        private_key: ec.EllipticCurvePrivateKey | None = None,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self._worker_id = worker_id
        self._private_key = private_key

    @property
    def worker_id(self) -> UUID | None:
        return self._worker_id

    def _create_auth_token(self) -> str:
        """Create a signed JWT for authentication.

        The JWT includes:
        - Header: algorithm (ES512) and issuer (worker_id)
        - Payload: issued at (iat) and expiration (exp) times
        """
        if self._worker_id is None:
            raise RuntimeError("Worker ID not set")
        if self._private_key is None:
            raise RuntimeError("Private key not set")

        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + JWT_EXPIRY_SECONDS,
        }
        headers = {
            "iss": str(self._worker_id),
        }
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="ES512",
            headers=headers,
        )

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with JWT authentication."""
        token = self._create_auth_token()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    async def stringify_choices(
        self,
        choice_type_id: UUID,
        local_ids: list[str],
    ) -> str | None:
        """Convert choice localIds to a string representation via backend API.

        Calls POST /worker/choice-types/:choiceTypeId/from-choices with
        worker authentication.

        Args:
            choice_type_id: The ChoiceType UUID
            local_ids: List of Choice localIds to stringify

        Returns:
            Stringified representation, or None if API call fails
        """
        if self._worker_id is None:
            raise RuntimeError("Worker ID not set")

        if not local_ids:
            return ""

        url = f"{self.api_base_url}/worker/choice-types/{choice_type_id}/from-choices"
        headers = self._get_auth_headers()
        payload = {"localIds": local_ids}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                if 200 <= response.status_code < 300:
                    data = response.json()
                    return data.get("data", {}).get("value", "")
                else:
                    print(f"[WorkerAPIClient] stringify_choices failed choiceTypeId={choice_type_id} status={response.status_code}")
                    print(f"[WorkerAPIClient] Request payload: {payload}")
                    print(f"[WorkerAPIClient] Response body: {response.text}")
                    return None
        except httpx.HTTPError as e:
            print(f"[WorkerAPIClient] stringify_choices request error choiceTypeId={choice_type_id} localIds={local_ids}: {e}")
            return None

    async def recalculate_exam_round_statistics(self, exam_round_id: UUID) -> bool:
        """Trigger statistics recalculation for an exam round via backend API.

        Calls POST /worker/statistics/exam-rounds/:examRoundId/recalculate

        Args:
            exam_round_id: The ExamRound UUID

        Returns:
            True if successful, False otherwise
        """
        if self._worker_id is None:
            raise RuntimeError("Worker ID not set")

        url = f"{self.api_base_url}/worker/statistics/exam-rounds/{exam_round_id}/recalculate"
        headers = self._get_auth_headers()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers)
                if 200 <= response.status_code < 300:
                    return True
                else:
                    print(f"[WorkerAPIClient] Statistics recalculation failed: {response.status_code}")
                    print(f"[WorkerAPIClient] Response body: {response.text}")
                    return False
        except httpx.HTTPError as e:
            print(f"[WorkerAPIClient] Statistics request failed: {e}")
            return False

    async def recalculate_exam_statistics(self, exam_id: UUID) -> bool:
        """Trigger exam-level statistics recalculation via backend API.

        Calls POST /worker/statistics/exams/:examId/recalculate

        Args:
            exam_id: The Exam UUID

        Returns:
            True if successful, False otherwise
        """
        if self._worker_id is None:
            raise RuntimeError("Worker ID not set")

        url = f"{self.api_base_url}/worker/statistics/exams/{exam_id}/recalculate"
        headers = self._get_auth_headers()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers)
                if 200 <= response.status_code < 300:
                    return True
                else:
                    print(f"[WorkerAPIClient] Exam statistics recalculation failed: {response.status_code}")
                    print(f"[WorkerAPIClient] Response body: {response.text}")
                    return False
        except httpx.HTTPError as e:
            print(f"[WorkerAPIClient] Exam statistics request failed: {e}")
            return False


# Global client instance
_client: WorkerAPIClient | None = None


def get_api_client() -> WorkerAPIClient | None:
    """Get the global API client instance."""
    return _client


def init_api_client(
    api_base_url: str | None = None,
    worker_id: UUID | None = None,
    private_key: ec.EllipticCurvePrivateKey | None = None,
) -> WorkerAPIClient:
    """Initialize the global API client instance."""
    global _client
    if api_base_url is None:
        api_base_url = os.getenv("API_BASE_URL", "http://localhost:3000")
    _client = WorkerAPIClient(api_base_url, worker_id, private_key)
    return _client
