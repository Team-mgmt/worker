"""Tests for worker.processors.base module."""

import base64
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import cv2
import numpy as np
import pytest

from worker.loggers.console import ConsoleLogger
from worker.processors.base import BaseProcessor
from worker.profiler import JobProfiler
from worker.types import Annotations, ImageProcessingParams, ProcessError


class ConcreteProcessor(BaseProcessor):
    """Concrete implementation for testing abstract base."""

    async def process(self, image, job_id, request_id, metadata):
        return {}


@pytest.fixture
def processor():
    mock_client = AsyncMock()
    mock_engine = MagicMock()
    p = ConcreteProcessor(mock_client, "test-bucket", mock_engine)
    return p


class TestBaseProcessorInit:
    def test_default_logger(self, processor):
        assert isinstance(processor._logger, ConsoleLogger)

    def test_default_profiler(self, processor):
        assert processor._profiler is None

    def test_set_logger(self, processor):
        logger = MagicMock()
        processor.set_logger(logger)
        assert processor._logger is logger

    def test_set_profiler(self, processor):
        profiler = JobProfiler()
        processor.set_profiler(profiler)
        assert processor._profiler is profiler


class TestTimeContextManagers:
    def test_time_no_profiler(self, processor):
        # Should be a no-op
        with processor._time("test"):
            pass

    def test_time_with_profiler(self, processor):
        profiler = JobProfiler()
        processor.set_profiler(profiler)
        with processor._time("test_step"):
            pass
        assert len(profiler._timings) == 1
        assert profiler._timings[0].name == "test_step"

    async def test_time_async_no_profiler(self, processor):
        async with processor._time_async("test"):
            pass

    async def test_time_async_with_profiler(self, processor):
        profiler = JobProfiler()
        processor.set_profiler(profiler)
        async with processor._time_async("async_step"):
            pass
        assert len(profiler._timings) == 1
        assert profiler._timings[0].name == "async_step"


class TestParseProcessingParams:
    def test_empty_metadata(self, processor):
        params = processor._parse_processing_params({})
        assert isinstance(params, ImageProcessingParams)
        assert params.denoise_ksize == 5

    def test_with_params(self, processor):
        metadata = {"processing_params": {"denoise_ksize": 9, "fill_ratio_threshold": 0.3}}
        params = processor._parse_processing_params(metadata)
        assert params.denoise_ksize == 9
        assert params.fill_ratio_threshold == 0.3

    def test_no_processing_params_key(self, processor):
        metadata = {"other_key": "value"}
        params = processor._parse_processing_params(metadata)
        assert params.denoise_ksize == 5  # default


class TestSaveAreaImage:
    def test_saves_rgb_image(self, processor):
        with tempfile.TemporaryDirectory() as tmpdir:
            from uuid import UUID

            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
            image = np.zeros((50, 50, 3), dtype=np.uint8)
            image[:, :] = [100, 150, 200]

            with patch("worker.processors.base.get_results_dir", return_value=tmpdir), \
                 patch("worker.processors.base.get_result_path", return_value=os.path.join(tmpdir, "area.png")):
                path = processor._save_area_image(req_id, job_id, image, "test_area")

            assert os.path.exists(path)

    def test_saves_grayscale_image(self, processor):
        with tempfile.TemporaryDirectory() as tmpdir:
            from uuid import UUID

            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
            image = np.zeros((50, 50), dtype=np.uint8)

            with patch("worker.processors.base.get_results_dir", return_value=tmpdir), \
                 patch("worker.processors.base.get_result_path", return_value=os.path.join(tmpdir, "area.png")):
                path = processor._save_area_image(req_id, job_id, image, "test_area")

            assert os.path.exists(path)


class TestAnnotatedImage:
    def test_annotated_image_qrcode(self, processor):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        annotations = [
            Annotations(
                data=np.array([[10, 10], [90, 10], [90, 90], [10, 90]], dtype=np.int32),
                type="qrcode_detected",
                value="http://example.com",
            )
        ]
        params = ImageProcessingParams()
        result = processor._annotated_image(image, annotations, params)
        assert result.shape == image.shape
        # Original should not be modified
        assert np.all(image == 0)

    def test_annotated_image_identifier(self, processor):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        annotations = [
            Annotations(
                data=np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.int32),
                type="area_inferred_child",
                value="IDENTIFIER_123_abc",
            )
        ]
        params = ImageProcessingParams()
        result = processor._annotated_image(image, annotations, params)
        assert result.shape == image.shape

    def test_annotated_image_problem(self, processor):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        annotations = [
            Annotations(
                data=np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.int32),
                type="area_inferred_child",
                value="PROBLEM_123_abc",
            )
        ]
        params = ImageProcessingParams()
        result = processor._annotated_image(image, annotations, params)
        assert result.shape == image.shape

    def test_annotated_image_other(self, processor):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        annotations = [
            Annotations(
                data=np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.int32),
                type="area_inferred_child",
                value="OTHER_123_abc",
            )
        ]
        params = ImageProcessingParams()
        result = processor._annotated_image(image, annotations, params)
        assert result.shape == image.shape

    def test_annotated_image_multiple(self, processor):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        annotations = [
            Annotations(data=np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.int32), type="qrcode_detected", value="qr"),
            Annotations(data=np.array([[60, 60], [90, 60], [90, 90], [60, 90]], dtype=np.int32), type="area_inferred_child", value="IDENTIFIER_x"),
        ]
        params = ImageProcessingParams()
        result = processor._annotated_image(image, annotations, params)
        assert result.shape == image.shape


class TestDetectQrcode:
    def _make_b64_uuid(self) -> tuple[UUID, str]:
        uid = uuid.uuid4()
        b64 = base64.urlsafe_b64encode(uid.bytes).decode().rstrip("=")
        return uid, b64

    def test_no_qrcode_found(self, processor):
        """No QR code in image should raise ProcessError."""
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        with patch("worker.processors.base.read_barcodes", return_value=[]):
            with pytest.raises(ProcessError, match="Expected 1 QR code"):
                processor._detect_qrcode(image)

    def test_multiple_qrcodes(self, processor):
        """Multiple QR codes should raise ProcessError."""
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        with patch("worker.processors.base.read_barcodes", return_value=[MagicMock(), MagicMock()]):
            with pytest.raises(ProcessError, match="Expected 1 QR code"):
                processor._detect_qrcode(image)

    def test_invalid_qr_content(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        barcode = MagicMock()
        barcode.text = "not-a-url"
        # urlparse won't have query params
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Missing exam round"):
                processor._detect_qrcode(image)

    def test_missing_exam_round(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        barcode = MagicMock()
        barcode.text = "https://example.com?a=abc"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Missing exam round"):
                processor._detect_qrcode(image)

    def test_missing_area_param(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        barcode = MagicMock()
        barcode.text = "https://example.com?e=abc"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Missing positional QR"):
                processor._detect_qrcode(image)

    def test_invalid_exam_round_format(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        _, b64_a = self._make_b64_uuid()
        barcode = MagicMock()
        barcode.text = f"https://example.com?e=short&a={b64_a}"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Invalid exam round id format"):
                processor._detect_qrcode(image)

    def test_invalid_area_format(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        _, b64_e = self._make_b64_uuid()
        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a=short"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Invalid positional QR code data format"):
                processor._detect_qrcode(image)

    def test_valid_qrcode(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        exam_round_id, b64_e = self._make_b64_uuid()
        area_id, b64_a = self._make_b64_uuid()

        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a={b64_a}"
        barcode.position.top_left = MagicMock(x=0.0, y=0.0)
        barcode.position.top_right = MagicMock(x=100.0, y=0.0)
        barcode.position.bottom_right = MagicMock(x=100.0, y=100.0)
        barcode.position.bottom_left = MagicMock(x=0.0, y=100.0)

        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            result_barcode, annotations, result_exam_round_id, result_area_id = processor._detect_qrcode(image)

        assert result_barcode is barcode
        assert result_exam_round_id == exam_round_id
        assert result_area_id == area_id
        assert len(annotations) == 1
        assert annotations[0]["type"] == "qrcode_detected"

    def test_multiple_e_params(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        _, b64_a = self._make_b64_uuid()
        barcode = MagicMock()
        barcode.text = f"https://example.com?e=a&e=b&a={b64_a}"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Invalid exam round id"):
                processor._detect_qrcode(image)

    def test_multiple_a_params(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        _, b64_e = self._make_b64_uuid()
        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a=a&a=b"
        with patch("worker.processors.base.read_barcodes", return_value=[barcode]):
            with pytest.raises(ProcessError, match="Invalid positional QR"):
                processor._detect_qrcode(image)


class TestDetectAllQrcodes:
    def _make_b64_uuid(self) -> tuple[UUID, str]:
        uid = uuid.uuid4()
        b64 = base64.urlsafe_b64encode(uid.bytes).decode().rstrip("=")
        return uid, b64

    def test_empty_image(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        with patch("worker.processors.base.read_barcodes", return_value=[]):
            result = processor._detect_all_qrcodes(image)
        assert result == {}

    def test_valid_qrcodes(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        area_id1, b64_1 = self._make_b64_uuid()
        area_id2, b64_2 = self._make_b64_uuid()

        bc1 = MagicMock()
        bc1.text = f"https://example.com?a={b64_1}"
        bc2 = MagicMock()
        bc2.text = f"https://example.com?a={b64_2}"

        with patch("worker.processors.base.read_barcodes", return_value=[bc1, bc2]):
            result = processor._detect_all_qrcodes(image)

        assert area_id1 in result
        assert area_id2 in result

    def test_skips_invalid_qrcodes(self, processor):
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        bc_invalid = MagicMock()
        bc_invalid.text = "not-a-url"

        bc_no_a = MagicMock()
        bc_no_a.text = "https://example.com?e=foo"

        bc_short_a = MagicMock()
        bc_short_a.text = "https://example.com?a=short"

        with patch("worker.processors.base.read_barcodes", return_value=[bc_invalid, bc_no_a, bc_short_a]):
            result = processor._detect_all_qrcodes(image)

        assert result == {}


class TestGetDatabaseRecords:
    async def test_exam_round_not_found(self, processor):
        mock_session = AsyncMock()

        with patch("worker.processors.base.get_by_id", AsyncMock(return_value=None)):
            with pytest.raises(ProcessError, match="Exam round not found"):
                await processor._get_database_records(
                    mock_session,
                    UUID("12345678-1234-5678-1234-567812345678"),
                    UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                )

    async def test_exam_not_found(self, processor):
        mock_session = AsyncMock()
        mock_exam_round = MagicMock()
        mock_exam_round.exam_id = UUID("22222222-2222-2222-2222-222222222222")

        async def mock_get_by_id(session, model, id):
            if model.__name__ == "ExamRound":
                return mock_exam_round
            return None

        with patch("worker.processors.base.get_by_id", side_effect=mock_get_by_id):
            with pytest.raises(ProcessError, match="Exam not found"):
                await processor._get_database_records(
                    mock_session,
                    UUID("12345678-1234-5678-1234-567812345678"),
                    UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                )

    async def test_exam_paper_not_found(self, processor):
        mock_session = AsyncMock()
        mock_exam_round = MagicMock()
        mock_exam_round.exam_id = UUID("22222222-2222-2222-2222-222222222222")
        mock_exam = MagicMock()
        mock_exam.exam_paper_id = UUID("33333333-3333-3333-3333-333333333333")

        call_count = [0]

        async def mock_get_by_id(session, model, id):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_exam_round
            if call_count[0] == 2:
                return mock_exam
            return None

        with patch("worker.processors.base.get_by_id", side_effect=mock_get_by_id):
            with pytest.raises(ProcessError, match="Exam paper not found"):
                await processor._get_database_records(
                    mock_session,
                    UUID("12345678-1234-5678-1234-567812345678"),
                    UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                )
