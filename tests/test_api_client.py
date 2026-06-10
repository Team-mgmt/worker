"""Tests for worker.api_client module."""

import time
from unittest.mock import patch
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from worker.api_client import (
    WorkerAPIClient,
    generate_es512_key_pair,
    get_api_client,
    init_api_client,
)


class TestGenerateES512KeyPair:
    def test_returns_private_key_and_pem(self):
        private_key, public_key_pem = generate_es512_key_pair()
        assert isinstance(private_key, ec.EllipticCurvePrivateKey)
        assert isinstance(public_key_pem, str)
        assert "BEGIN PUBLIC KEY" in public_key_pem
        assert "END PUBLIC KEY" in public_key_pem

    def test_key_uses_p521_curve(self):
        private_key, _ = generate_es512_key_pair()
        assert isinstance(private_key.curve, ec.SECP521R1)

    def test_unique_keys(self):
        _, pem1 = generate_es512_key_pair()
        _, pem2 = generate_es512_key_pair()
        assert pem1 != pem2


class TestWorkerAPIClient:
    @pytest.fixture
    def client_with_keys(self):
        private_key, public_key_pem = generate_es512_key_pair()
        worker_id = UUID("12345678-1234-5678-1234-567812345678")
        client = WorkerAPIClient("https://api.example.com/", worker_id, private_key)
        return client, private_key, public_key_pem, worker_id

    def test_init_strips_trailing_slash(self):
        client = WorkerAPIClient("https://api.example.com/")
        assert client.api_base_url == "https://api.example.com"

    def test_worker_id_property(self):
        worker_id = UUID("12345678-1234-5678-1234-567812345678")
        client = WorkerAPIClient("https://api.example.com", worker_id=worker_id)
        assert client.worker_id == worker_id

    def test_worker_id_none(self):
        client = WorkerAPIClient("https://api.example.com")
        assert client.worker_id is None

    def test_create_auth_token_raises_without_worker_id(self):
        client = WorkerAPIClient("https://api.example.com")
        with pytest.raises(RuntimeError, match="Worker ID not set"):
            client._create_auth_token()

    def test_create_auth_token_raises_without_private_key(self):
        worker_id = UUID("12345678-1234-5678-1234-567812345678")
        client = WorkerAPIClient("https://api.example.com", worker_id=worker_id)
        with pytest.raises(RuntimeError, match="Private key not set"):
            client._create_auth_token()

    def test_create_auth_token_valid(self, client_with_keys):
        client, private_key, public_key_pem, worker_id = client_with_keys
        token = client._create_auth_token()

        assert isinstance(token, str)
        # Decode without verification to check structure
        decoded = jwt.decode(token, options={"verify_signature": False})
        assert "iat" in decoded
        assert "exp" in decoded
        assert decoded["exp"] - decoded["iat"] == 300

        headers = jwt.get_unverified_header(token)
        assert headers["alg"] == "ES512"
        assert headers["iss"] == str(worker_id)

    def test_get_auth_headers(self, client_with_keys):
        client, _, _, _ = client_with_keys
        headers = client._get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["Content-Type"] == "application/json"

    async def test_stringify_choices_empty_list(self, client_with_keys):
        client, _, _, _ = client_with_keys
        choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        result = await client.stringify_choices(choice_type_id, [])
        assert result == ""

    async def test_stringify_choices_raises_without_worker_id(self):
        client = WorkerAPIClient("https://api.example.com")
        with pytest.raises(RuntimeError, match="Worker ID not set"):
            await client.stringify_choices(UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"), ["a"])

    async def test_stringify_choices_success(self, client_with_keys, respx_mock):
        import httpx
        import respx

        client, _, _, worker_id = client_with_keys
        choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/choice-types/{choice_type_id}/from-choices").mock(
            return_value=httpx.Response(200, json={"data": {"value": "42"}})
        )

        result = await client.stringify_choices(choice_type_id, ["4", "2"])
        assert result == "42"

    async def test_stringify_choices_api_failure(self, client_with_keys, respx_mock):
        import httpx
        import respx

        client, _, _, _ = client_with_keys
        choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/choice-types/{choice_type_id}/from-choices").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.stringify_choices(choice_type_id, ["1"])
        assert result is None

    async def test_stringify_choices_network_error(self, client_with_keys, respx_mock):
        import httpx
        import respx

        client, _, _, _ = client_with_keys
        choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/choice-types/{choice_type_id}/from-choices").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await client.stringify_choices(choice_type_id, ["1"])
        assert result is None

    async def test_recalculate_success(self, client_with_keys, respx_mock):
        import httpx

        client, _, _, _ = client_with_keys
        exam_round_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/statistics/exam-rounds/{exam_round_id}/recalculate").mock(
            return_value=httpx.Response(200)
        )

        result = await client.recalculate_exam_round_statistics(exam_round_id)
        assert result is True

    async def test_recalculate_failure(self, client_with_keys, respx_mock):
        import httpx

        client, _, _, _ = client_with_keys
        exam_round_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/statistics/exam-rounds/{exam_round_id}/recalculate").mock(
            return_value=httpx.Response(500)
        )

        result = await client.recalculate_exam_round_statistics(exam_round_id)
        assert result is False

    async def test_recalculate_raises_without_worker_id(self):
        client = WorkerAPIClient("https://api.example.com")
        with pytest.raises(RuntimeError, match="Worker ID not set"):
            await client.recalculate_exam_round_statistics(UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"))

    async def test_recalculate_network_error(self, client_with_keys, respx_mock):
        import httpx

        client, _, _, _ = client_with_keys
        exam_round_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/statistics/exam-rounds/{exam_round_id}/recalculate").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await client.recalculate_exam_round_statistics(exam_round_id)
        assert result is False

    async def test_recalculate_exam_statistics_success(self, client_with_keys, respx_mock):
        import httpx

        client, _, _, _ = client_with_keys
        exam_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/statistics/exams/{exam_id}/recalculate").mock(
            return_value=httpx.Response(200)
        )

        result = await client.recalculate_exam_statistics(exam_id)
        assert result is True

    async def test_recalculate_exam_statistics_failure(self, client_with_keys, respx_mock):
        import httpx

        client, _, _, _ = client_with_keys
        exam_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        respx_mock.post(f"https://api.example.com/worker/statistics/exams/{exam_id}/recalculate").mock(
            return_value=httpx.Response(500)
        )

        result = await client.recalculate_exam_statistics(exam_id)
        assert result is False

    async def test_recalculate_exam_statistics_raises_without_worker_id(self):
        client = WorkerAPIClient("https://api.example.com")
        with pytest.raises(RuntimeError, match="Worker ID not set"):
            await client.recalculate_exam_statistics(UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"))


class TestGlobalClient:
    def test_init_and_get(self):
        client = init_api_client("https://example.com")
        assert get_api_client() is client
        assert client.api_base_url == "https://example.com"

    def test_init_default_url(self):
        with patch.dict("os.environ", {"API_BASE_URL": "https://custom.api.com"}, clear=False):
            client = init_api_client()
            assert client.api_base_url == "https://custom.api.com"

    def test_init_with_credentials(self):
        private_key, _ = generate_es512_key_pair()
        worker_id = UUID("12345678-1234-5678-1234-567812345678")
        client = init_api_client("https://api.com", worker_id, private_key)
        assert client.worker_id == worker_id
