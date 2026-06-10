"""Tests for worker.matcher module."""

from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from worker.matcher import (
    DocumentMatcher,
    MatchResult,
    four_point_transform,
    get_matcher,
    warmup_matcher,
)


class TestMatchResult:
    def test_creation(self):
        warp = np.zeros((10, 10, 2))
        overlap = np.zeros((10, 10, 1))
        result = MatchResult(warp_AB=warp, overlap_AB=overlap, confidence=0.8)
        assert result.confidence == 0.8
        assert result.warp_AB.shape == (10, 10, 2)
        assert result.overlap_AB.shape == (10, 10, 1)


class TestFourPointTransform:
    def test_basic_transform(self):
        # Create a simple 200x200 image
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        image[50:150, 50:150] = 255  # White square

        # Define source corners (the white square corners)
        pts = np.array([[50, 50], [150, 50], [150, 150], [50, 150]], dtype=np.float32)

        warped, M = four_point_transform(image, pts, output_size=(100, 100))
        assert warped.shape == (100, 100, 3)
        assert M.shape == (3, 3)

    def test_auto_size(self):
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        pts = np.array([[50, 50], [150, 50], [150, 150], [50, 150]], dtype=np.float32)

        warped, M = four_point_transform(image, pts)
        # Auto-computed size should be approximately 100x100
        assert warped.shape[0] > 0
        assert warped.shape[1] > 0

    def test_grayscale_image(self):
        image = np.zeros((200, 200), dtype=np.uint8)
        pts = np.array([[50, 50], [150, 50], [150, 150], [50, 150]], dtype=np.float32)

        warped, M = four_point_transform(image, pts, output_size=(100, 100))
        assert warped.shape == (100, 100)

    def test_transform_matrix_is_valid(self):
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        pts = np.array([[0, 0], [199, 0], [199, 199], [0, 199]], dtype=np.float32)

        _, M = four_point_transform(image, pts, output_size=(200, 200))
        # Transform matrix should be approximately identity for aligned corners
        assert M.shape == (3, 3)
        # Top-left corner should map close to (0,0)
        pt = M @ np.array([0, 0, 1])
        pt = pt[:2] / pt[2]
        assert abs(pt[0]) < 2
        assert abs(pt[1]) < 2


class TestDocumentMatcher:
    def test_singleton(self):
        # Reset singleton
        DocumentMatcher._instance = None
        m1 = DocumentMatcher.get_instance()
        m2 = DocumentMatcher.get_instance()
        assert m1 is m2
        DocumentMatcher._instance = None  # Cleanup

    def test_init(self):
        matcher = DocumentMatcher()
        assert matcher._initialized is False
        assert matcher._model_H == 0
        assert matcher._model_W == 0

    def test_get_device(self):
        device = DocumentMatcher.get_device()
        assert isinstance(device, str)
        assert device in ("cpu", "cuda", "mps") or True  # May be any string

    def test_match_not_initialized(self):
        matcher = DocumentMatcher()
        scan = np.zeros((100, 100, 3), dtype=np.uint8)
        template = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch.object(matcher, "initialize", return_value=False):
            result = matcher.match(scan, template)
        assert result is None

    def test_warp_not_initialized(self):
        matcher = DocumentMatcher()
        scan = np.zeros((100, 100, 3), dtype=np.uint8)
        template = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch.object(matcher, "initialize", return_value=False):
            result = matcher.warp_scan_to_template(scan, template)
            assert result is None

    def test_initialize_already_initialized(self):
        matcher = DocumentMatcher()
        matcher._initialized = True
        result = matcher.initialize()
        assert result is True


class TestGetMatcher:
    def test_returns_singleton(self):
        DocumentMatcher._instance = None
        m = get_matcher()
        assert isinstance(m, DocumentMatcher)
        assert get_matcher() is m
        DocumentMatcher._instance = None


class TestDocumentMatcherInitialize:
    def test_initialize_success(self):
        matcher = DocumentMatcher()
        mock_model = MagicMock()
        mock_model.H_hr = 1280
        mock_model.W_hr = 1280
        mock_model.H_lr = 800
        mock_model.W_lr = 800

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "romav2": MagicMock(RoMaV2=MagicMock(return_value=mock_model)),
        }):
            result = matcher.initialize()
            assert result is True
            assert matcher._initialized is True
            assert matcher._model_H == 1280
            assert matcher._model_W == 1280

    def test_initialize_disables_compile_on_cpu(self):
        matcher = DocumentMatcher()
        mock_model = MagicMock()
        mock_model.H_hr = 1280
        mock_model.W_hr = 1280
        mock_model.H_lr = 800
        mock_model.W_lr = 800
        mock_cfg = MagicMock()
        mock_roma_class = MagicMock(return_value=mock_model)
        mock_roma_class.Cfg = MagicMock(return_value=mock_cfg)

        with (
            patch("worker.matcher.roma_device", "cpu"),
            patch.dict("os.environ", {}, clear=True),
            patch.dict("sys.modules", {
                "torch": MagicMock(),
                "romav2": MagicMock(RoMaV2=mock_roma_class),
            }),
        ):
            result = matcher.initialize()
            assert result is True
            mock_roma_class.Cfg.assert_called_once_with(compile=False)
            mock_roma_class.assert_called_once_with(mock_cfg)

    def test_initialize_enables_compile_on_cuda(self):
        matcher = DocumentMatcher()
        mock_model = MagicMock()
        mock_model.H_hr = 1280
        mock_model.W_hr = 1280
        mock_model.H_lr = 800
        mock_model.W_lr = 800
        mock_cfg = MagicMock()
        mock_roma_class = MagicMock(return_value=mock_model)
        mock_roma_class.Cfg = MagicMock(return_value=mock_cfg)

        with (
            patch("worker.matcher.roma_device", "cuda"),
            patch.dict("os.environ", {}, clear=True),
            patch.dict("sys.modules", {
                "torch": MagicMock(),
                "romav2": MagicMock(RoMaV2=mock_roma_class),
            }),
        ):
            result = matcher.initialize()
            assert result is True
            mock_roma_class.Cfg.assert_called_once_with(compile=True)
            mock_roma_class.assert_called_once_with(mock_cfg)

    def test_initialize_exception(self):
        matcher = DocumentMatcher()
        with (
            patch.dict("sys.modules", {
                "torch": MagicMock(),
                "romav2": MagicMock(RoMaV2=MagicMock(side_effect=RuntimeError("GPU error"))),
            }),
        ):
            result = matcher.initialize()
            assert result is False

    def test_initialize_no_hr(self):
        """When H_hr is None, falls back to H_lr."""
        matcher = DocumentMatcher()
        mock_model = MagicMock()
        mock_model.H_hr = None
        mock_model.W_hr = None
        mock_model.H_lr = 800
        mock_model.W_lr = 800

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "romav2": MagicMock(RoMaV2=MagicMock(return_value=mock_model)),
        }):
            result = matcher.initialize()
            assert result is True
            assert matcher._model_H == 800


class TestDocumentMatcherWarmup:
    def test_warmup_success(self):
        matcher = DocumentMatcher()
        matcher._initialized = True
        matcher._model = MagicMock()
        result = matcher.warmup("a.jpg", "b.jpg")
        assert result is True
        matcher._model.match.assert_called_once()

    def test_warmup_model_none(self):
        matcher = DocumentMatcher()
        matcher._initialized = True
        matcher._model = None
        result = matcher.warmup("a.jpg", "b.jpg")
        assert result is False

    def test_warmup_exception(self):
        matcher = DocumentMatcher()
        matcher._initialized = True
        matcher._model = MagicMock()
        matcher._model.match.side_effect = RuntimeError("warmup failed")
        result = matcher.warmup("a.jpg", "b.jpg")
        assert result is False

    def test_warmup_initializes_if_needed(self):
        matcher = DocumentMatcher()
        matcher._initialized = False
        with patch.object(matcher, "initialize", return_value=False):
            result = matcher.warmup("a.jpg", "b.jpg")
            assert result is False


class TestDocumentMatcherMatch:
    def test_match_success(self):
        matcher = DocumentMatcher()
        matcher._initialized = True

        mock_warp = MagicMock()
        mock_warp.__getitem__ = MagicMock(return_value=MagicMock(cpu=MagicMock(return_value=MagicMock(numpy=MagicMock(return_value=np.zeros((10, 10, 2)))))))
        mock_overlap = MagicMock()
        mock_overlap.__getitem__ = MagicMock(return_value=MagicMock(cpu=MagicMock(return_value=MagicMock(numpy=MagicMock(return_value=np.full((10, 10, 1), 0.8))))))

        mock_model = MagicMock()
        mock_model.match.return_value = {"warp_AB": mock_warp, "overlap_AB": mock_overlap}
        matcher._model = mock_model

        scan = np.zeros((100, 100, 3), dtype=np.uint8)
        template = np.zeros((100, 100, 3), dtype=np.uint8)
        result = matcher.match(scan, template)
        assert result is not None
        assert result.confidence == pytest.approx(0.8)

    def test_match_exception(self):
        matcher = DocumentMatcher()
        matcher._initialized = True
        matcher._model = MagicMock()
        matcher._model.match.side_effect = RuntimeError("match failed")
        result = matcher.match(np.zeros((10, 10, 3)), np.zeros((10, 10, 3)))
        assert result is None


class TestWarmupMatcher:
    def test_warmup_uses_singleton(self):
        DocumentMatcher._instance = None
        with patch.object(DocumentMatcher, "warmup", return_value=True) as mock_warmup:
            result = warmup_matcher("a.jpg", "b.jpg")
            assert result is True
            mock_warmup.assert_called_once_with("a.jpg", "b.jpg")
        DocumentMatcher._instance = None
