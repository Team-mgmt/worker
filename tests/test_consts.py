"""Tests for worker.consts module."""

from worker.consts import BASE64_URL_REGEX, JOB_MAX_RETRIES, JOB_TIMEOUT_MINUTES, POSITIONS, WORKER_HEARTBEAT_INTERVAL_SECONDS


class TestConstants:
    def test_positions(self):
        assert POSITIONS == ["LT", "RT", "RB", "LB"]
        assert len(POSITIONS) == 4

    def test_job_timeout(self):
        assert JOB_TIMEOUT_MINUTES == 5

    def test_job_max_retries(self):
        assert JOB_MAX_RETRIES == 3

    def test_heartbeat_interval(self):
        assert WORKER_HEARTBEAT_INTERVAL_SECONDS == 3


class TestBase64UrlRegex:
    def test_valid_base64url(self):
        assert BASE64_URL_REGEX.match("ABCDEFghijklmnop1234") is not None
        assert BASE64_URL_REGEX.match("abc_def-ghi") is not None
        assert BASE64_URL_REGEX.match("A") is not None

    def test_invalid_base64url(self):
        assert BASE64_URL_REGEX.match("abc+def") is None
        assert BASE64_URL_REGEX.match("abc=def") is None
        assert BASE64_URL_REGEX.match("abc def") is None
        assert BASE64_URL_REGEX.match("") is None

    def test_22_char_base64url(self):
        """22-char base64url strings are used for UUID encoding."""
        assert BASE64_URL_REGEX.match("a" * 22) is not None
