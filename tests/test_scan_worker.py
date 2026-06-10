"""Tests for worker.worker.scan module."""

import asyncio
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import numpy as np
import pytest

from worker.types import ImageProcessingParams, ProcessError, ProcessResult
from worker.worker.scan import ScanWorker


@pytest.fixture
def mock_scan_worker():
    client = AsyncMock()
    engine = MagicMock()
    worker_id = UUID("11111111-1111-1111-1111-111111111111")
    worker = ScanWorker(client=client, bucket_name="test-bucket", engine=engine, worker_id=worker_id)
    return worker


class TestScanWorkerInit:
    def test_init(self, mock_scan_worker):
        assert mock_scan_worker.bucket_name == "test-bucket"
        assert mock_scan_worker.worker_id == UUID("11111111-1111-1111-1111-111111111111")
        assert mock_scan_worker._shutdown_requested is False
        assert mock_scan_worker._ready is False

    def test_request_shutdown(self, mock_scan_worker):
        assert mock_scan_worker._shutdown_requested is False
        mock_scan_worker.request_shutdown()
        assert mock_scan_worker._shutdown_requested is True

    def test_ready_state(self, mock_scan_worker):
        assert mock_scan_worker.is_ready() is False
        mock_scan_worker.set_ready(True)
        assert mock_scan_worker.is_ready() is True
        mock_scan_worker.set_ready(False)
        assert mock_scan_worker.is_ready() is False


class TestActivityTracking:
    async def test_update_and_get_activity(self, mock_scan_worker):
        before = time.time()
        await mock_scan_worker.update_activity()
        after = time.time()

        last = await mock_scan_worker.get_last_activity_time()
        assert before <= last <= after

    async def test_concurrent_activity_updates(self, mock_scan_worker):
        """Activity updates should be safe under concurrent access."""

        async def update():
            await mock_scan_worker.update_activity()

        await asyncio.gather(*[update() for _ in range(10)])
        last = await mock_scan_worker.get_last_activity_time()
        assert last > 0


class TestDeriveStudentIdFallback:
    def test_empty_results(self, mock_scan_worker):
        result = mock_scan_worker._derive_student_id_fallback({})
        assert result == ""

    def test_single_detections(self, mock_scan_worker):
        results = {0: ["1"], 1: ["2"], 2: ["3"]}
        result = mock_scan_worker._derive_student_id_fallback(results)
        assert result == "123"

    def test_blank_detection(self, mock_scan_worker):
        results = {0: ["1"], 1: [], 2: ["3"]}
        result = mock_scan_worker._derive_student_id_fallback(results)
        assert result == "1_3"

    def test_multiple_detections(self, mock_scan_worker):
        results = {0: ["1", "2"], 1: ["3"]}
        result = mock_scan_worker._derive_student_id_fallback(results)
        assert result == "*3"

    def test_sorted_order(self, mock_scan_worker):
        results = {2: ["C"], 0: ["A"], 1: ["B"]}
        result = mock_scan_worker._derive_student_id_fallback(results)
        assert result == "ABC"


class TestCalculateScore:
    def test_empty_results(self, mock_scan_worker):
        score = mock_scan_worker._calculate_score({}, {})
        assert score == 0.0

    def test_correct_answer(self, mock_scan_worker):
        problem_id = UUID("12345678-1234-5678-1234-567812345678")
        problem = MagicMock()
        problem.answer = ["A"]
        problem.score = 5.0

        result = mock_scan_worker._calculate_score(
            {problem_id: ["A"]},
            {problem_id: problem},
        )
        assert result == 5.0

    def test_wrong_answer(self, mock_scan_worker):
        problem_id = UUID("12345678-1234-5678-1234-567812345678")
        problem = MagicMock()
        problem.answer = ["A"]
        problem.score = 5.0

        result = mock_scan_worker._calculate_score(
            {problem_id: ["B"]},
            {problem_id: problem},
        )
        assert result == 0.0

    def test_multi_answer_correct(self, mock_scan_worker):
        problem_id = UUID("12345678-1234-5678-1234-567812345678")
        problem = MagicMock()
        problem.answer = ["A", "C"]
        problem.score = 10.0

        # Order doesn't matter
        result = mock_scan_worker._calculate_score(
            {problem_id: ["C", "A"]},
            {problem_id: problem},
        )
        assert result == 10.0

    def test_multiple_problems(self, mock_scan_worker):
        p1 = UUID("12345678-1234-5678-1234-567812345678")
        p2 = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        prob1 = MagicMock()
        prob1.answer = ["A"]
        prob1.score = 5.0

        prob2 = MagicMock()
        prob2.answer = ["B"]
        prob2.score = 3.0

        result = mock_scan_worker._calculate_score(
            {p1: ["A"], p2: ["B"]},
            {p1: prob1, p2: prob2},
        )
        assert result == 8.0

    def test_missing_problem_in_map(self, mock_scan_worker):
        problem_id = UUID("12345678-1234-5678-1234-567812345678")
        result = mock_scan_worker._calculate_score({problem_id: ["A"]}, {})
        assert result == 0.0

    def test_problem_without_answer(self, mock_scan_worker):
        problem_id = UUID("12345678-1234-5678-1234-567812345678")
        problem = MagicMock()
        problem.answer = None
        problem.score = 5.0

        result = mock_scan_worker._calculate_score(
            {problem_id: ["A"]},
            {problem_id: problem},
        )
        assert result == 0.0


class TestCreateProcessor:
    def test_creates_v1_processor(self, mock_scan_worker):
        processor = mock_scan_worker._create_processor(1.0)
        from worker.processors.v1 import ProcessorV1

        assert isinstance(processor, ProcessorV1)

    def test_invalid_version_raises(self, mock_scan_worker):
        with pytest.raises(ValueError):
            mock_scan_worker._create_processor(99.0)


class TestCleanupProcessedImages:
    def test_cleanup_results_dir(self, mock_scan_worker):
        with tempfile.TemporaryDirectory() as tmpdir:
            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

            results_dir = os.path.join(tmpdir, "results")
            os.makedirs(results_dir)
            with open(os.path.join(results_dir, "file.png"), "w") as f:
                f.write("test")

            with (
                patch("worker.worker.scan.get_results_dir", return_value=results_dir),
                patch("worker.worker.scan.get_request_results_dir", return_value=os.path.join(tmpdir, "req")),
                patch("worker.worker.scan.IMAGES_DIR", tmpdir),
            ):
                mock_scan_worker._cleanup_processed_images(req_id, job_id, "img.png")

            assert not os.path.exists(results_dir)

    def test_cleanup_input_image(self, mock_scan_worker):
        with tempfile.TemporaryDirectory() as tmpdir:
            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

            # Create the input image file
            input_path = os.path.join(tmpdir, f"{req_id}.png")
            with open(input_path, "w") as f:
                f.write("test")

            with (
                patch("worker.worker.scan.get_results_dir", return_value="/nonexistent"),
                patch("worker.worker.scan.get_request_results_dir", return_value="/nonexistent"),
                patch("worker.worker.scan.IMAGES_DIR", tmpdir),
            ):
                mock_scan_worker._cleanup_processed_images(req_id, job_id, "path/to/img.png")

            assert not os.path.exists(input_path)


class TestDeriveStudentId:
    async def test_empty_results(self, mock_scan_worker):
        result = await mock_scan_worker._derive_student_id({}, [])
        assert result == ""

    async def test_no_api_client_uses_fallback(self, mock_scan_worker):
        with patch("worker.worker.scan.get_api_client", return_value=None):
            result = await mock_scan_worker._derive_student_id({0: ["1"], 1: ["2"]}, [])
            assert result == "12"

    async def test_api_client_stringify(self, mock_scan_worker):
        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="42")

        area = MagicMock()
        area.index = 0
        area.area_type = MagicMock()
        area.area_type.choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: ["4", "2"]}, [area])
            assert result == "42"

    async def test_api_client_failure_fallback(self, mock_scan_worker):
        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value=None)

        area = MagicMock()
        area.index = 0
        area.area_type = MagicMock()
        area.area_type.choice_type_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: ["4"]}, [area])
            assert result == "4"

    async def test_missing_area_for_index(self, mock_scan_worker):
        api_client = AsyncMock()

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: ["1"]}, [])
            assert result == "_"

    async def test_no_choice_type_single_detection(self, mock_scan_worker):
        api_client = AsyncMock()

        area = MagicMock()
        area.index = 0
        area.area_type = MagicMock()
        area.area_type.choice_type_id = None

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: ["5"]}, [area])
            assert result == "5"

    async def test_no_choice_type_multiple_detection(self, mock_scan_worker):
        api_client = AsyncMock()

        area = MagicMock()
        area.index = 0
        area.area_type = MagicMock()
        area.area_type.choice_type_id = None

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: ["5", "6"]}, [area])
            assert result == "*"

    async def test_empty_detected_for_index(self, mock_scan_worker):
        api_client = AsyncMock()
        area = MagicMock()
        area.index = 0
        area.area_type = MagicMock()

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_student_id({0: []}, [area])
            assert result == "_"


class TestIso8601UtcNow:
    def test_format_is_iso8601_utc_millis_z(self):
        import re

        from worker.worker.scan import _iso8601_utc_now

        value = _iso8601_utc_now()
        # e.g. 2026-05-16T12:34:56.789Z
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value), value


class TestDeriveMetadataPayload:
    """Verify the METADATA stringification per ExamPaperArea.id.

    Unlike _derive_student_id, this returns a dict keyed by area_id (as str) so
    DraftSubmission.metadata / ExamSubmission.metadata JSONB columns can be looked
    up by area without losing the area identity.
    """

    async def test_empty_results(self, mock_scan_worker):
        result = await mock_scan_worker._derive_metadata_payload({}, [])
        assert result == {}

    async def test_stringifies_per_area(self, mock_scan_worker):
        area_id_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        area_id_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        choice_a = UUID("11111111-2222-3333-4444-555555555555")
        choice_b = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")

        area_a = MagicMock()
        area_a.id = area_id_a
        area_a.area_type = MagicMock()
        area_a.area_type.choice_type_id = choice_a

        area_b = MagicMock()
        area_b.id = area_id_b
        area_b.area_type = MagicMock()
        area_b.area_type.choice_type_id = choice_b

        async def stringify(choice_type_id, local_ids):
            if choice_type_id == choice_a:
                return "Room-203"
            if choice_type_id == choice_b:
                return "B"
            return None

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(side_effect=stringify)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id_a: ["2", "0", "3"], area_id_b: ["B"]},
                [area_a, area_b],
            )

        assert result == {str(area_id_a): "Room-203", str(area_id_b): "B"}

    async def test_no_choice_type_skips_area(self, mock_scan_worker):
        """An area whose area_type has no choice_type_id is silently skipped — METADATA
        is opportunistic; a misconfigured area shouldn't drop the whole scan."""
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = None

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="should-not-be-called")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]},
                [area],
            )

        assert result == {}
        api_client.stringify_choices.assert_not_awaited()

    async def test_stringify_returns_none_skips(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value=None)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]},
                [area],
            )

        assert result == {}

    async def test_stringify_raises_skips(self, mock_scan_worker):
        """An exception thrown by stringify_choices must not abort the scan."""
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]},
                [area],
            )

        assert result == {}

    async def test_no_api_client_skips(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id

        with patch("worker.worker.scan.get_api_client", return_value=None):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]},
                [area],
            )

        assert result == {}

    async def test_unknown_area_id_skips(self, mock_scan_worker):
        """metadata_results may carry an area_id not in metadata_areas if upstream
        filtering drifts — skip rather than KeyError."""
        known_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        unknown_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        known_area = MagicMock()
        known_area.id = known_id
        known_area.area_type = MagicMock()
        known_area.area_type.choice_type_id = choice_id

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="X")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {unknown_id: ["1"], known_id: ["2"]},
                [known_area],
            )

        assert result == {str(known_id): "X"}

    async def test_exam_name_area_injects_name_history(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.display_name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="Jane Doe")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload({area_id: ["1"]}, [area])

        assert result[str(area_id)] == "Jane Doe"
        assert result["currentNameEditId"] == "00000000-0000-0000-0000-000000000000"
        assert len(result["nameHistory"]) == 1
        entry = result["nameHistory"][0]
        assert entry["id"] == "00000000-0000-0000-0000-000000000000"
        assert entry["name"] == "Jane Doe"
        assert entry["source"] == "WORKER"
        import re

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", entry["editedAt"])

    async def test_exam_name_empty_value_no_injection(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.display_name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload({area_id: []}, [area])

        assert "nameHistory" not in result
        assert "currentNameEditId" not in result

    async def test_exam_name_none_value_no_injection(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.display_name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value=None)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload({area_id: ["1"]}, [area])

        assert "nameHistory" not in result

    async def test_non_exam_name_metadata_unaffected(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.name = "ROOM"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="203")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload({area_id: ["2", "0", "3"]}, [area])

        assert result == {str(area_id): "203"}

    async def test_multiple_exam_name_areas_first_resolving_wins(self, mock_scan_worker):
        area_id_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        area_id_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        choice_a = UUID("11111111-2222-3333-4444-555555555555")
        choice_b = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")

        area_a = MagicMock()
        area_a.id = area_id_a
        area_a.area_type = MagicMock()
        area_a.area_type.choice_type_id = choice_a
        area_a.area_type.display_name = "EXAM_NAME"

        area_b = MagicMock()
        area_b.id = area_id_b
        area_b.area_type = MagicMock()
        area_b.area_type.choice_type_id = choice_b
        area_b.area_type.display_name = "EXAM_NAME"

        async def stringify(choice_type_id, local_ids):
            return "First" if choice_type_id == choice_a else "Second"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(side_effect=stringify)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id_a: ["1"], area_id_b: ["2"]},
                [area_a, area_b],
            )

        assert result["nameHistory"][0]["name"] == "First"

    async def test_multiple_exam_name_first_empty_later_resolves_wins(self, mock_scan_worker):
        area_id_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        area_id_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        choice_a = UUID("11111111-2222-3333-4444-555555555555")
        choice_b = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")

        area_a = MagicMock()
        area_a.id = area_id_a
        area_a.area_type = MagicMock()
        area_a.area_type.choice_type_id = choice_a
        area_a.area_type.display_name = "EXAM_NAME"

        area_b = MagicMock()
        area_b.id = area_id_b
        area_b.area_type = MagicMock()
        area_b.area_type.choice_type_id = choice_b
        area_b.area_type.display_name = "EXAM_NAME"

        async def stringify(choice_type_id, local_ids):
            return "" if choice_type_id == choice_a else "Second"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(side_effect=stringify)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id_a: ["1"], area_id_b: ["2"]},
                [area_a, area_b],
            )

        assert result["nameHistory"][0]["name"] == "Second"


class TestIsExamNameUnresolved:
    def _area(self, type_name):
        area = MagicMock()
        area.area_type = MagicMock()
        area.area_type.display_name = type_name
        return area

    def test_false_when_no_exam_name_area(self, mock_scan_worker):
        areas = [self._area("ROOM"), self._area("CLASS")]
        assert mock_scan_worker._is_exam_name_unresolved(areas, {"x": "y"}) is False

    def test_false_when_exam_name_resolved(self, mock_scan_worker):
        areas = [self._area("EXAM_NAME")]
        payload = {"nameHistory": [{"name": "Jane"}]}
        assert mock_scan_worker._is_exam_name_unresolved(areas, payload) is False

    def test_true_when_exam_name_area_but_no_name_history(self, mock_scan_worker):
        areas = [self._area("EXAM_NAME"), self._area("ROOM")]
        assert mock_scan_worker._is_exam_name_unresolved(areas, {}) is True

    def test_handles_area_with_no_area_type(self, mock_scan_worker):
        bad = MagicMock()
        bad.area_type = None
        assert mock_scan_worker._is_exam_name_unresolved([bad], {}) is False


class TestForceDraftForUnresolvedName:
    def test_true_when_unresolved_and_not_teacher(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(True, "STUDENT") is True

    def test_false_when_unresolved_but_teacher(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(True, "TEACHER") is False

    def test_false_when_resolved(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(False, "STUDENT") is False


class TestCreateLogger:
    def test_creates_database_logger(self, mock_scan_worker):
        from worker.loggers.database import DatabaseLogger

        job_id = UUID("12345678-1234-5678-1234-567812345678")
        req_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        logger = mock_scan_worker._create_logger(job_id, req_id)
        assert isinstance(logger, DatabaseLogger)
        assert logger.job_id == job_id
        assert logger.scan_request_id == req_id


class TestSendHeartbeat:
    async def test_sends_heartbeat(self, mock_scan_worker):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_scan_worker.session_factory = factory

        job_id = UUID("12345678-1234-5678-1234-567812345678")
        await mock_scan_worker._send_heartbeat(job_id)
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestUploadResults:
    async def test_upload_results(self, mock_scan_worker):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create temporary image files
            for name in ["annotated_cropped.png", "flattened.png", "threshold.png", "area1.png"]:
                with open(os.path.join(tmpdir, name), "wb") as f:
                    f.write(b"\x89PNG" + b"\x00" * 100)

            org_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
            req_id = UUID("11111111-1111-1111-1111-111111111111")

            result = ProcessResult(
                organization_id=org_id,
                exam_id=UUID("22222222-2222-2222-2222-222222222222"),
                exam_round_id=UUID("33333333-3333-3333-3333-333333333333"),
                annotations=[{"data": np.array([[1, 2], [3, 4]]), "type": "qrcode_detected", "value": "test"}],
                annotations_cropped=[{"data": np.array([[5, 6]]), "type": "area", "value": "v"}],
                image_annotated_cropped_path=os.path.join(tmpdir, "annotated_cropped.png"),
                image_flattened_path=os.path.join(tmpdir, "flattened.png"),
                image_threshold_path=os.path.join(tmpdir, "threshold.png"),
                area_image_paths={"area_1": os.path.join(tmpdir, "area1.png")},
                area_metrics={"area_1": {"version": 1, "is_filled": True, "fill_ratio": 0.8}},
                student_info_results={0: ["1"]},
                problem_results={0: ["A"]},
                option_results={},
                processing_params=ImageProcessingParams(),
                processing_meta={"bubble_shape": "ellipse"},
            )

            await mock_scan_worker.upload_results(job_id, req_id, result, "scans/original.png")

            # Should have called S3 operations
            mock_scan_worker.client.copy_object.assert_called_once()
            assert mock_scan_worker.client.put_object.call_count >= 7  # images + JSON files


class TestCleanupProcessedImagesEmptyDir:
    def test_cleanup_removes_empty_request_dir(self, mock_scan_worker):
        with tempfile.TemporaryDirectory() as tmpdir:
            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

            # Create empty request directory
            req_dir = os.path.join(tmpdir, "req_dir")
            os.makedirs(req_dir)

            with (
                patch("worker.worker.scan.get_results_dir", return_value="/nonexistent"),
                patch("worker.worker.scan.get_request_results_dir", return_value=req_dir),
                patch("worker.worker.scan.IMAGES_DIR", tmpdir),
            ):
                mock_scan_worker._cleanup_processed_images(req_id, job_id, "img.png")

            assert not os.path.exists(req_dir)


class TestStartLoop:
    """Test the main start() job processing loop."""

    @pytest.fixture
    def worker_for_start(self):
        client = AsyncMock()
        engine = MagicMock()
        worker_id = UUID("11111111-1111-1111-1111-111111111111")
        w = ScanWorker(client=client, bucket_name="test-bucket", engine=engine, worker_id=worker_id)

        # Mock session factory
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.add = MagicMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        w.session_factory = factory
        w._mock_session = mock_session
        return w

    def _make_execute_mock(self, worker, scan_request=None, job=None):
        """Create a mock execute that handles stale job cleanup + atomic pick.

        Returns scan_request on the atomic pick call, or None (no jobs).
        Triggers shutdown in the finally block (cleanup) so the loop exits.
        """
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            # Calls 1-4: stale job cleanup queries
            if call_count[0] <= 4:
                result.scalar_one_or_none.return_value = None
                return result
            # Call 5: atomic pick UPDATE ... RETURNING
            if call_count[0] == 5:
                result.scalar_one_or_none.return_value = scan_request
                return result
            # Call 6: INSERT ScanRequestJob (only if scan_request was found)
            if call_count[0] == 6 and job is not None:
                result.scalar_one.return_value = job
                return result
            # All subsequent calls: generic mock
            result.scalar_one_or_none.return_value = None
            result.scalar_one.return_value = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.one.return_value = MagicMock(has_draft=False, has_submission=False)
            result.rowcount = 0
            return result

        return AsyncMock(side_effect=mock_execute)

    def _build_submission_context(self, *, verification_enabled: bool, source: str = "STUDENT") -> SimpleNamespace:
        import uuid7

        org_id = UUID("12345678-1234-5678-1234-567812345678")
        exam_id = UUID("22222222-2222-2222-2222-222222222222")
        exam_round_id = UUID("33333333-3333-3333-3333-333333333333")
        exam_paper_id = UUID("44444444-4444-4444-4444-444444444444")
        problem_set_id = UUID("55555555-5555-5555-5555-555555555555")
        problem_id = UUID("66666666-6666-6666-6666-666666666666")

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {"processor_version": 1.0}
        scan_request.source = source

        job = MagicMock()
        job.id = uuid7.create()

        exam = MagicMock()
        exam.id = exam_id
        exam.exam_paper_id = exam_paper_id
        exam.student_verification_enabled = verification_enabled

        area = MagicMock()
        area.id = UUID("77777777-7777-7777-7777-777777777777")
        area.index = 0
        area.area_type = MagicMock()
        area.area_type.base_type = "PROBLEM"
        area.area_type.choice_type = None

        problem_set = MagicMock()
        problem_set.id = problem_set_id
        problem_set.default = True
        problem_set.area_id = None
        problem_set.area_value = None

        problem = MagicMock()
        problem.id = problem_id
        problem.exam_paper_area = area
        problem.answer = ["A"]
        problem.score = 5.0

        process_result = ProcessResult(
            organization_id=org_id,
            exam_id=exam_id,
            exam_round_id=exam_round_id,
            annotations=[],
            annotations_cropped=[],
            image_annotated_cropped_path="/tmp/test.png",
            image_flattened_path="/tmp/test2.png",
            image_threshold_path="/tmp/test3.png",
            area_image_paths={},
            area_metrics={},
            student_info_results={},
            problem_results={0: ["A"]},
            option_results={},
            processing_params=ImageProcessingParams(),
            processing_meta={"bubble_shape": "rect"},
        )

        return SimpleNamespace(
            org_id=org_id,
            exam_id=exam_id,
            exam_round_id=exam_round_id,
            scan_request=scan_request,
            job=job,
            exam=exam,
            area=area,
            problem_set=problem_set,
            problem=problem,
            process_result=process_result,
        )

    async def test_shutdown_immediately(self, worker_for_start):
        """Worker exits when shutdown is requested before any jobs."""
        worker_for_start._shutdown_requested = True
        await worker_for_start.start()

    async def test_no_jobs_available_then_shutdown(self, worker_for_start, capsys):
        """Worker sleeps when no jobs, shuts down on next iteration."""
        # Return None for atomic pick (no jobs available)
        worker_for_start._mock_session.execute = self._make_execute_mock(worker_for_start, scan_request=None)

        async def mock_sleep(duration):
            # After sleeping (no jobs), request shutdown
            worker_for_start.request_shutdown()

        with patch("worker.worker.scan.asyncio.sleep", side_effect=mock_sleep):
            await worker_for_start.start()

        captured = capsys.readouterr()
        assert "Graceful shutdown completed" in captured.out

    async def test_handles_process_error(self, worker_for_start, capsys):
        """Worker handles ProcessError and marks job as failed."""
        import uuid7

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {}
        scan_request.source = "STUDENT"

        job = MagicMock()
        job.id = uuid7.create()

        worker_for_start._mock_session.execute = self._make_execute_mock(worker_for_start, scan_request=scan_request, job=job)

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with patch("worker.worker.scan.prepare_image", AsyncMock(side_effect=ProcessError("Image error", code="IMAGE_ERROR"))):
            await worker_for_start.start()

        # Verify job was marked as failed (multiple execute calls for error handling)
        worker_for_start._mock_session.commit.assert_called()

    async def test_handles_generic_exception(self, worker_for_start, capsys):
        """Worker handles unexpected exceptions and marks job as failed."""
        import uuid7

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {}
        scan_request.source = "STUDENT"

        job = MagicMock()
        job.id = uuid7.create()

        worker_for_start._mock_session.execute = self._make_execute_mock(worker_for_start, scan_request=scan_request, job=job)

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with patch("worker.worker.scan.prepare_image", AsyncMock(side_effect=RuntimeError("Unexpected!"))):
            await worker_for_start.start()

        worker_for_start._mock_session.commit.assert_called()

    async def test_full_job_with_submission(self, worker_for_start, capsys):
        """Test full job processing through to ExamSubmission creation (verification disabled)."""
        import uuid7

        org_id = UUID("12345678-1234-5678-1234-567812345678")
        exam_id = UUID("22222222-2222-2222-2222-222222222222")
        exam_round_id = UUID("33333333-3333-3333-3333-333333333333")
        exam_paper_id = UUID("44444444-4444-4444-4444-444444444444")
        problem_set_id = UUID("55555555-5555-5555-5555-555555555555")
        problem_id = UUID("66666666-6666-6666-6666-666666666666")

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {"processor_version": 1.0}
        scan_request.source = "STUDENT"

        job = MagicMock()
        job.id = uuid7.create()

        # Mock Exam
        mock_exam = MagicMock()
        mock_exam.id = exam_id
        mock_exam.exam_paper_id = exam_paper_id
        mock_exam.student_verification_enabled = False

        # Mock areas
        mock_area = MagicMock()
        mock_area.id = UUID("77777777-7777-7777-7777-777777777777")
        mock_area.index = 0
        mock_area.area_type = MagicMock()
        mock_area.area_type.base_type = "PROBLEM"

        # Mock problem set (default)
        mock_ps = MagicMock()
        mock_ps.id = problem_set_id
        mock_ps.default = True
        mock_ps.area_id = None
        mock_ps.area_value = None

        # Mock problem
        mock_problem = MagicMock()
        mock_problem.id = problem_id
        mock_problem.exam_paper_area = mock_area
        mock_problem.answer = ["A"]
        mock_problem.score = 5.0

        process_result = ProcessResult(
            organization_id=org_id,
            exam_id=exam_id,
            exam_round_id=exam_round_id,
            annotations=[],
            annotations_cropped=[],
            image_annotated_cropped_path="/tmp/test.png",
            image_flattened_path="/tmp/test2.png",
            image_threshold_path="/tmp/test3.png",
            area_image_paths={},
            area_metrics={},
            student_info_results={},
            problem_results={0: ["A"]},
            option_results={},
            processing_params=ImageProcessingParams(),
            processing_meta={"bubble_shape": "ellipse"},
        )

        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()

            # Stale job cleanup (4 calls)
            if call_count[0] <= 4:
                result.scalar_one_or_none.return_value = None
                return result
            # Atomic pick
            if call_count[0] == 5:
                result.scalar_one_or_none.return_value = scan_request
                return result
            # Insert job
            if call_count[0] == 6:
                result.scalar_one.return_value = job
                return result
            # Commit after job insert
            if call_count[0] == 7:
                return result
            # Update org_id on job
            if call_count[0] == 8:
                return result
            # Commit after org_id update (handled by session.commit mock)
            # Select Exam
            if call_count[0] == 9:
                result.scalar_one.return_value = mock_exam
                return result
            # Select areas with area_type
            if call_count[0] == 10:
                result.scalars.return_value.all.return_value = [mock_area]
                return result
            # Select problem sets
            if call_count[0] == 11:
                result.scalars.return_value.all.return_value = [mock_ps]
                return result
            # Select exam problems
            if call_count[0] == 12:
                result.scalars.return_value.all.return_value = [mock_problem]
                return result
            # Check existing submission for request
            if call_count[0] == 13:
                result.scalar_one_or_none.return_value = None
                return result
            # Check existing submission for student
            if call_count[0] == 14:
                result.scalar_one_or_none.return_value = None
                return result
            # Discard drafts
            if call_count[0] == 15:
                result.rowcount = 0
                return result

            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        worker_for_start._mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=None),
        ):
            await worker_for_start.start()

        # Session should have committed (submission created)
        worker_for_start._mock_session.commit.assert_called()
        # Processor should have been called
        mock_processor.process.assert_called_once()

    def _build_exam_name_context(self, *, source: str, stringified_name: str) -> SimpleNamespace:
        """Build a single-problem job context plus an EXAM_NAME METADATA area.

        ``stringify_choices`` is mocked to return ``stringified_name`` so an empty
        string exercises the unresolved-name path and a non-empty string the
        resolved path. Construction mirrors ``test_full_job_with_submission``.
        """
        import uuid7

        org_id = UUID("12345678-1234-5678-1234-567812345678")
        exam_id = UUID("22222222-2222-2222-2222-222222222222")
        exam_round_id = UUID("33333333-3333-3333-3333-333333333333")
        exam_paper_id = UUID("44444444-4444-4444-4444-444444444444")
        problem_set_id = UUID("55555555-5555-5555-5555-555555555555")
        problem_id = UUID("66666666-6666-6666-6666-666666666666")
        exam_name_area_id = UUID("88888888-8888-8888-8888-888888888888")
        choice_type_id = UUID("99999999-9999-9999-9999-999999999999")

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {"processor_version": 1.0}
        scan_request.source = source

        job = MagicMock()
        job.id = uuid7.create()

        exam = MagicMock()
        exam.id = exam_id
        exam.exam_paper_id = exam_paper_id
        exam.student_verification_enabled = False

        problem_area = MagicMock()
        problem_area.id = UUID("77777777-7777-7777-7777-777777777777")
        problem_area.index = 0
        problem_area.area_type = MagicMock()
        problem_area.area_type.base_type = "PROBLEM"
        problem_area.area_type.choice_type = None

        # EXAM_NAME METADATA area: present in the areas the worker loads, with a
        # choice_type_id so _derive_metadata_payload calls stringify_choices.
        exam_name_area = MagicMock()
        exam_name_area.id = exam_name_area_id
        exam_name_area.index = 1
        exam_name_area.area_type = MagicMock()
        exam_name_area.area_type.base_type = "METADATA"
        exam_name_area.area_type.display_name = "EXAM_NAME"
        exam_name_area.area_type.choice_type_id = choice_type_id
        exam_name_area.area_type.choice_type = None

        problem_set = MagicMock()
        problem_set.id = problem_set_id
        problem_set.default = True
        problem_set.area_id = None
        problem_set.area_value = None

        problem = MagicMock()
        problem.id = problem_id
        problem.exam_paper_area = problem_area
        problem.exam_paper_area_id = problem_area.id
        problem.answer = ["A"]
        problem.score = 5.0

        process_result = ProcessResult(
            organization_id=org_id,
            exam_id=exam_id,
            exam_round_id=exam_round_id,
            annotations=[],
            annotations_cropped=[],
            image_annotated_cropped_path="/tmp/test.png",
            image_flattened_path="/tmp/test2.png",
            image_threshold_path="/tmp/test3.png",
            area_image_paths={},
            area_metrics={},
            student_info_results={},
            problem_results={0: ["A"]},
            option_results={},
            processing_params=ImageProcessingParams(),
            processing_meta={"bubble_shape": "ellipse"},
            metadata_results={exam_name_area_id: ["1"]},
        )

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value=stringified_name)

        return SimpleNamespace(
            org_id=org_id,
            exam_id=exam_id,
            exam_round_id=exam_round_id,
            scan_request=scan_request,
            job=job,
            exam=exam,
            problem_area=problem_area,
            exam_name_area=exam_name_area,
            problem_set=problem_set,
            problem=problem,
            process_result=process_result,
            api_client=api_client,
        )

    def _make_exam_name_execute_mock(self, ctx):
        """execute() side-effect mirroring the proven call sequence of
        test_invalid_student_scan_creates_draft_submission, but the areas query
        (call 7) also returns the EXAM_NAME METADATA area. Generic late calls
        satisfy both the draft has_draft/has_submission EXISTS query (result.one)
        and the direct-submission existence/discard queries."""
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 3:
                result.scalar_one_or_none.return_value = ctx.scan_request
                return result
            if call_count[0] == 4:
                result.scalar_one.return_value = ctx.job
                return result
            if call_count[0] == 6:
                result.scalar_one.return_value = ctx.exam
                return result
            if call_count[0] == 7:
                result.scalars.return_value.all.return_value = [ctx.problem_area, ctx.exam_name_area]
                return result
            if call_count[0] == 8:
                result.scalars.return_value.all.return_value = [ctx.problem_set]
                return result
            if call_count[0] == 9:
                result.scalars.return_value.all.return_value = [ctx.problem]
                return result
            result.scalar_one_or_none.return_value = None
            result.one.return_value = SimpleNamespace(has_draft=False, has_submission=False)
            result.rowcount = 0
            return result

        return AsyncMock(side_effect=mock_execute)

    async def _run_exam_name_job(self, worker_for_start, ctx):
        """Drive a full job through start() with the EXAM_NAME context and return
        the list of types added to the session (newest call order preserved)."""
        worker_for_start._mock_session.execute = self._make_exam_name_execute_mock(ctx)

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=ctx.process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=ctx.api_client),
        ):
            await worker_for_start.start()

        return worker_for_start._mock_session.add.call_args_list

    async def test_unresolved_exam_name_forces_draft_for_student(self, worker_for_start):
        """STUDENT scan, verification disabled, valid result, but EXAM_NAME
        stringifies to "" -> force DraftSubmission (no ExamSubmission)."""
        from worker.generated.models import DraftSubmission, ExamSubmission

        ctx = self._build_exam_name_context(source="STUDENT", stringified_name="")
        add_calls = await self._run_exam_name_job(worker_for_start, ctx)

        added_types = [type(call.args[0]) for call in add_calls]
        assert DraftSubmission in added_types
        assert ExamSubmission not in added_types

    async def test_unresolved_exam_name_still_direct_for_teacher(self, worker_for_start):
        """TEACHER scan is exempt from the force-draft rule even when EXAM_NAME
        is unresolved -> ExamSubmission created directly."""
        from worker.generated.models import DraftSubmission, ExamSubmission

        ctx = self._build_exam_name_context(source="TEACHER", stringified_name="")
        add_calls = await self._run_exam_name_job(worker_for_start, ctx)

        added_types = [type(call.args[0]) for call in add_calls]
        assert ExamSubmission in added_types
        assert DraftSubmission not in added_types

    async def test_resolved_exam_name_direct_submission_has_name_keys(self, worker_for_start):
        """STUDENT scan, verification disabled, valid result, EXAM_NAME resolves
        to "Jane Doe" -> ExamSubmission whose metadata seeds nameHistory."""
        from worker.generated.models import ExamSubmission

        ctx = self._build_exam_name_context(source="STUDENT", stringified_name="Jane Doe")
        add_calls = await self._run_exam_name_job(worker_for_start, ctx)

        exam_submissions = [call.args[0] for call in add_calls if type(call.args[0]).__name__ == "ExamSubmission"]
        assert len(exam_submissions) == 1
        submission = exam_submissions[0]
        assert isinstance(submission, ExamSubmission)
        assert submission.metadata_["currentNameEditId"] == "00000000-0000-0000-0000-000000000000"
        assert submission.metadata_["nameHistory"][0]["name"] == "Jane Doe"
        assert submission.metadata_["nameHistory"][0]["source"] == "WORKER"

    async def test_integrity_error_handling(self, worker_for_start, capsys):
        """Worker handles IntegrityError for concurrent submissions."""
        import uuid7

        from sqlalchemy.exc import IntegrityError

        scan_request = MagicMock()
        scan_request.id = uuid7.create()
        scan_request.key = "scans/test.png"
        scan_request.metadata_ = {}
        scan_request.source = "STUDENT"

        job = MagicMock()
        job.id = uuid7.create()

        worker_for_start._mock_session.execute = self._make_execute_mock(worker_for_start, scan_request=scan_request, job=job)

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        # Simulate IntegrityError during processing
        orig = Exception("ExamSubmission_examRoundId_studentId_unique_active")
        with patch("worker.worker.scan.prepare_image", AsyncMock(side_effect=IntegrityError("", {}, orig))):
            await worker_for_start.start()

        # Should have rolled back and committed error status
        worker_for_start._mock_session.rollback.assert_called()

    async def test_invalid_student_scan_creates_draft_submission(self, worker_for_start):
        from worker.generated.models import DraftSubmission, DraftSubmissionAnswer

        ctx = self._build_submission_context(verification_enabled=True, source="STUDENT")
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 3:
                result.scalar_one_or_none.return_value = ctx.scan_request
                return result
            if call_count[0] == 4:
                result.scalar_one.return_value = ctx.job
                return result
            if call_count[0] == 6:
                result.scalar_one.return_value = ctx.exam
                return result
            if call_count[0] == 7:
                result.scalars.return_value.all.return_value = [ctx.area]
                return result
            if call_count[0] == 8:
                result.scalars.return_value.all.return_value = [ctx.problem_set]
                return result
            if call_count[0] == 9:
                result.scalars.return_value.all.return_value = [ctx.problem]
                return result
            if call_count[0] == 10:
                result.one.return_value = SimpleNamespace(has_draft=False, has_submission=False)
                return result
            if call_count[0] == 11:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 12:
                result.rowcount = 0
                return result
            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        worker_for_start._mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=ctx.process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()
        mock_logger = MagicMock()
        mock_logger.info = AsyncMock()
        mock_logger.warn = AsyncMock()
        mock_logger.error = AsyncMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "_create_logger", return_value=mock_logger),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_derive_metadata_payload", AsyncMock(return_value={})),
            patch.object(worker_for_start, "_is_valid_scan_result", return_value=False),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=None),
        ):
            await worker_for_start.start()

        added_types = [type(call.args[0]) for call in worker_for_start._mock_session.add.call_args_list]
        assert DraftSubmission in added_types
        assert DraftSubmissionAnswer in added_types
        mock_logger.info.assert_any_await("Creating DraftSubmission (studentVerificationEnabled=true, source=STUDENT)")

    async def test_invalid_student_scan_drops_when_result_already_exists(self, worker_for_start):
        from worker.generated.models import DraftSubmission, ExamSubmission

        ctx = self._build_submission_context(verification_enabled=True, source="STUDENT")
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 3:
                result.scalar_one_or_none.return_value = ctx.scan_request
                return result
            if call_count[0] == 4:
                result.scalar_one.return_value = ctx.job
                return result
            if call_count[0] == 6:
                result.scalar_one.return_value = ctx.exam
                return result
            if call_count[0] == 7:
                result.scalars.return_value.all.return_value = [ctx.area]
                return result
            if call_count[0] == 8:
                result.scalars.return_value.all.return_value = [ctx.problem_set]
                return result
            if call_count[0] == 9:
                result.scalars.return_value.all.return_value = [ctx.problem]
                return result
            if call_count[0] == 10:
                result.one.return_value = SimpleNamespace(has_draft=True, has_submission=False)
                return result
            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        worker_for_start._mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=ctx.process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()
        mock_logger = MagicMock()
        mock_logger.info = AsyncMock()
        mock_logger.warn = AsyncMock()
        mock_logger.error = AsyncMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "_create_logger", return_value=mock_logger),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_derive_metadata_payload", AsyncMock(return_value={})),
            patch.object(worker_for_start, "_is_valid_scan_result", return_value=False),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=None),
        ):
            await worker_for_start.start()

        added_types = [type(call.args[0]) for call in worker_for_start._mock_session.add.call_args_list]
        assert DraftSubmission not in added_types
        assert ExamSubmission not in added_types
        mock_logger.info.assert_any_await("Dropped: ScanRequest already has a draft or submission")

    async def test_teacher_duplicate_submission_soft_deletes_and_recreates(self, worker_for_start):
        from worker.generated.models import ExamSubmission, ExamSubmissionAnswer

        ctx = self._build_submission_context(verification_enabled=True, source="TEACHER")
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 3:
                result.scalar_one_or_none.return_value = ctx.scan_request
                return result
            if call_count[0] == 4:
                result.scalar_one.return_value = ctx.job
                return result
            if call_count[0] == 6:
                result.scalar_one.return_value = ctx.exam
                return result
            if call_count[0] == 7:
                result.scalars.return_value.all.return_value = [ctx.area]
                return result
            if call_count[0] == 8:
                result.scalars.return_value.all.return_value = [ctx.problem_set]
                return result
            if call_count[0] == 9:
                result.scalars.return_value.all.return_value = [ctx.problem]
                return result
            if call_count[0] == 10:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 11:
                result.scalar_one_or_none.return_value = UUID("99999999-9999-9999-9999-999999999999")
                return result
            if call_count[0] in (12, 13):
                return result
            if call_count[0] == 14:
                result.rowcount = 0
                return result
            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        worker_for_start._mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=ctx.process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()
        mock_logger = MagicMock()
        mock_logger.info = AsyncMock()
        mock_logger.warn = AsyncMock()
        mock_logger.error = AsyncMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "_create_logger", return_value=mock_logger),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_derive_metadata_payload", AsyncMock(return_value={})),
            patch.object(worker_for_start, "_is_valid_scan_result", return_value=True),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=None),
        ):
            await worker_for_start.start()

        added_types = [type(call.args[0]) for call in worker_for_start._mock_session.add.call_args_list]
        assert ExamSubmission in added_types
        assert ExamSubmissionAnswer in added_types
        mock_logger.info.assert_any_await("Teacher scan: soft-deleting existing ExamSubmission for studentId=12345")

    async def test_student_duplicate_submission_fails_with_process_error(self, worker_for_start):
        from worker.generated.models import ExamSubmission

        ctx = self._build_submission_context(verification_enabled=False, source="STUDENT")
        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] <= 2:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 3:
                result.scalar_one_or_none.return_value = ctx.scan_request
                return result
            if call_count[0] == 4:
                result.scalar_one.return_value = ctx.job
                return result
            if call_count[0] == 6:
                result.scalar_one.return_value = ctx.exam
                return result
            if call_count[0] == 7:
                result.scalars.return_value.all.return_value = [ctx.area]
                return result
            if call_count[0] == 8:
                result.scalars.return_value.all.return_value = [ctx.problem_set]
                return result
            if call_count[0] == 9:
                result.scalars.return_value.all.return_value = [ctx.problem]
                return result
            if call_count[0] == 10:
                result.scalar_one_or_none.return_value = None
                return result
            if call_count[0] == 11:
                result.scalar_one_or_none.return_value = UUID("99999999-9999-9999-9999-999999999999")
                return result
            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        worker_for_start._mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=ctx.process_result)
        mock_processor.set_logger = MagicMock()
        mock_processor.set_profiler = MagicMock()
        mock_logger = MagicMock()
        mock_logger.info = AsyncMock()
        mock_logger.warn = AsyncMock()
        mock_logger.error = AsyncMock()

        def shutdown_on_cleanup(*args, **kwargs):
            worker_for_start.request_shutdown()

        worker_for_start._cleanup_processed_images = shutdown_on_cleanup

        with (
            patch("worker.worker.scan.prepare_image", AsyncMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), 1.0))),
            patch.object(worker_for_start, "_create_processor", return_value=mock_processor),
            patch.object(worker_for_start, "_create_logger", return_value=mock_logger),
            patch.object(worker_for_start, "upload_results", AsyncMock()),
            patch.object(worker_for_start, "_derive_student_id", AsyncMock(return_value="12345")),
            patch.object(worker_for_start, "_derive_metadata_payload", AsyncMock(return_value={})),
            patch.object(worker_for_start, "_is_valid_scan_result", return_value=True),
            patch.object(worker_for_start, "_send_heartbeat", AsyncMock()),
            patch("worker.worker.scan.get_api_client", return_value=None),
        ):
            await worker_for_start.start()

        added_types = [type(call.args[0]) for call in worker_for_start._mock_session.add.call_args_list]
        assert ExamSubmission not in added_types
        mock_logger.error.assert_any_await("ExamSubmission already exists for studentId=12345")
