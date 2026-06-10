"""Tests for worker.processors.v1 module."""

# ruff: noqa: E402

import os
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import cv2
import numpy as np
import pytest

sys.modules.setdefault("cairosvg", MagicMock())
romav2_module = types.ModuleType("romav2")
romav2_device_module = types.ModuleType("romav2.device")
romav2_device_module.device = "cpu"
romav2_module.device = romav2_device_module
sys.modules.setdefault("romav2", romav2_module)
sys.modules.setdefault("romav2.device", romav2_device_module)

from worker.generated.models import Exampaperareabasetype
from worker.processors.v1 import ProcessorV1
from worker.types import ImageProcessingParams, ProcessError


@pytest.fixture
def mock_matcher():
    matcher = MagicMock()
    matcher._initialized = False
    return matcher


@pytest.fixture
def processor_v1(mock_matcher):
    mock_client = AsyncMock()
    mock_engine = MagicMock()
    with patch.object(ProcessorV1, "__init__", lambda self, *a, **kw: None):
        p = ProcessorV1.__new__(ProcessorV1)
        p.client = mock_client
        p.bucket_name = "test-bucket"
        p.engine = mock_engine
        p.session_factory = MagicMock()
        p._logger = MagicMock()
        p._profiler = None
        p._matcher = mock_matcher
        # Tests bypass BaseProcessor.__init__, so install the no-op observer
        # default that `process()` would otherwise rebind for debug runs.
        from worker.processor_observer import ProcessorObserver
        p._observer = ProcessorObserver()
    return p


class TestCheckFilledArea:
    def test_filled_area(self, processor_v1):
        """Image with mostly black pixels should be detected as filled."""
        image = np.zeros((20, 20), dtype=np.uint8)  # All black
        template = np.full((20, 20), 255, dtype=np.uint8)  # Blank template
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["is_filled"] is True
        assert result["fill_ratio"] == pytest.approx(1.0)
        assert result["version"] == 1

    def test_empty_area(self, processor_v1):
        """Image with mostly white pixels should not be detected as filled."""
        image = np.full((20, 20), 255, dtype=np.uint8)  # All white
        template = np.full((20, 20), 255, dtype=np.uint8)  # Blank template
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["is_filled"] is False
        assert result["fill_ratio"] == pytest.approx(0.0)

    def test_partial_fill(self, processor_v1):
        """Image with some black should be detected based on threshold."""
        image = np.full((100, 100), 255, dtype=np.uint8)
        template = np.full((100, 100), 255, dtype=np.uint8)  # Blank template
        # Fill 60% with black
        image[:60, :] = 0
        params = ImageProcessingParams(
            fill_ratio_threshold=0.5, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["is_filled"] is True
        assert 0.55 < result["fill_ratio"] < 0.65

    def test_zero_area(self, processor_v1):
        """Zero-size image should return not filled."""
        image = np.zeros((0, 0), dtype=np.uint8)
        template = np.zeros((0, 0), dtype=np.uint8)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["is_filled"] is False
        assert result["fill_ratio"] == 0.0

    def test_threshold_boundary(self, processor_v1):
        """Test behavior at exactly the threshold."""
        image = np.full((100, 100), 255, dtype=np.uint8)
        template = np.full((100, 100), 255, dtype=np.uint8)  # Blank template
        image[:40, :] = 0  # Exactly 40%
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        # At exactly threshold, should not be filled (> not >=)
        assert result["is_filled"] is False

    def test_background_subtraction(self, processor_v1):
        """Pre-printed template pixels are excluded from both the numerator
        and the denominator: the ratio is over the user-fillable region
        (inscribed ellipse minus template ink), not the whole ellipse.
        Band y∈[0,20) is template ink; band y∈[0,50) is scan ink, so the
        scan covers band y∈[20,50) of the user-fillable region (which is
        the ellipse over rows [20,100)).
        """
        image = np.full((100, 100), 255, dtype=np.uint8)
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[:20, :] = 0  # 20% of bbox rows pre-printed
        image[:50, :] = 0  # 50% of bbox rows ink (covers template + user fill)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        # ellipse∩rows[20,50)  ÷  ellipse∩rows[20,100)  ≈  0.42
        # (upper-half ellipse minus the y<20 cap, divided by ellipse
        # without the y<20 cap). Stays under the 0.4 threshold by a hair.
        assert 0.40 < result["fill_ratio"] < 0.45
        assert result["is_filled"] is True

    def test_template_overscan_does_not_produce_negative(self, processor_v1):
        """When the scan's ink is entirely *within* the template's ink
        (e.g. alignment shifted ink in but added nothing), the
        user-fillable region sees no marks and fill_ratio is 0 — without
        relying on a max(0, …) clamp that the prior count-subtraction
        formula needed.
        """
        image = np.full((100, 100), 255, dtype=np.uint8)
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[:30, :] = 0  # template inks rows 0..30
        image[:10, :] = 0  # scan inks rows 0..10 (subset of template)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["fill_ratio"] == 0.0
        assert result["is_filled"] is False

    def test_ignores_pixels_outside_ellipse(self, processor_v1):
        """Pixels outside the inscribed ellipse must not influence fill_ratio."""
        # All-white scan with black ink only in the bbox corners (outside ellipse).
        image = np.full((100, 100), 255, dtype=np.uint8)
        image[:10, :10] = 0
        image[:10, 90:] = 0
        image[90:, :10] = 0
        image[90:, 90:] = 0
        template = np.full((100, 100), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.05, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["fill_ratio"] == pytest.approx(0.0, abs=1e-3)
        assert result["is_filled"] is False

    def test_fully_filled_bubble_with_preprint_reads_full(self, processor_v1):
        """Regression: a fully-filled IDENTIFIER bubble with a pre-printed
        digit/letter inside it must read ≈ 1.0, not (1 − preprint_fraction).

        Previously the formula divided ``user_marks − template_marks`` by
        ``ellipse_area``, so a fully-marked bubble whose template label
        covered ~10% of the inscribed ellipse capped at ~0.9. That made
        confidently-filled bubbles look borderline and shrank the headroom
        operators have to push ``fill_ratio_threshold`` upward.
        Concrete instance from DEV: scan job
        ``019dfdb1-abde-7194-812e-32c0af36841d`` IDENTIFIER bubble I0
        reported 0.895 instead of ~1.0.
        """
        image = np.zeros((100, 100), dtype=np.uint8)  # fully inked
        # Template pre-prints a chunky block inside the ellipse simulating
        # a printed "0"/"1"/etc label centered in the bubble. Coverage is
        # similar to a real OMR digit (~9% of the bbox / ~12% of the
        # inscribed ellipse).
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[40:70, 40:70] = 0
        params = ImageProcessingParams(
            fill_ratio_threshold=0.5, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["fill_ratio"] == pytest.approx(1.0)
        assert result["is_filled"] is True

    def test_empty_bubble_with_preprint_reads_zero(self, processor_v1):
        """Counterpart to the fully-filled regression: an *unfilled*
        bubble whose template has a pre-printed label inside must read
        ≈ 0.0, not the fraction of the ellipse covered by the label.
        Without excluding template ink from the numerator, the formula
        would falsely credit the printed label as "user fill".
        """
        image = np.full((100, 100), 255, dtype=np.uint8)  # blank scan
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[40:70, 40:70] = 0
        params = ImageProcessingParams(
            fill_ratio_threshold=0.5, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["fill_ratio"] == pytest.approx(0.0)
        assert result["is_filled"] is False

    def test_template_covers_entire_ellipse_returns_zero(self, processor_v1):
        """Pathological: if the template inks the entire inscribed ellipse,
        the user-fillable region is empty and fill_ratio must be 0 (no
        ZeroDivisionError, no spurious detection).
        """
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.zeros((20, 20), dtype=np.uint8)  # all template ink
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4, use_template_baseline_fill_delta=False, bubble_measurement_shape="ellipse"
        )
        result = processor_v1._check_filled_area(image, template, params)
        assert result["fill_ratio"] == 0.0
        assert result["is_filled"] is False

    def test_absolute_mode_reports_legacy_behavior(self, processor_v1):
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.full((20, 20), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4,
            use_template_baseline_fill_delta=False,
            bubble_measurement_shape="ellipse",
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.9)

        assert result["is_filled"] is True
        assert result["fill_ratio"] == pytest.approx(1.0)
        assert result["baseline_fill_ratio"] == pytest.approx(0.0)
        assert result["delta_fill_ratio"] == pytest.approx(1.0)

    def test_delta_threshold_boundary(self, processor_v1):
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.full((20, 20), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_measurement_shape="ellipse",
            baseline_fill_ratio_offset=0.0,
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.61)

        assert result["fill_ratio"] == pytest.approx(1.0)
        assert result["baseline_fill_ratio"] == pytest.approx(0.61)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(0.61)
        assert result["delta_fill_ratio"] == pytest.approx(0.39)
        assert result["is_filled"] is False

    def test_delta_mode_detects_strong_mark(self, processor_v1):
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.full((20, 20), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_measurement_shape="ellipse",
            baseline_fill_ratio_offset=0.0,
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.13)

        assert result["delta_fill_ratio"] == pytest.approx(0.87)
        assert result["is_filled"] is True

    def test_ellipse_delta_mode_ignores_baseline_offset(self, processor_v1):
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.full((20, 20), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_measurement_shape="ellipse",
            baseline_fill_ratio_offset=0.10,
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.61)

        assert result["baseline_fill_ratio"] == pytest.approx(0.61)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(0.61)
        assert result["delta_fill_ratio"] == pytest.approx(0.39)
        assert result["is_filled"] is False

    def test_delta_mode_uses_same_ellipse_basis_for_scan_and_baseline(self, processor_v1):
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[:20, :] = 0
        image = template.copy()
        image[20:50, :] = 0
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_measurement_shape="ellipse",
            baseline_fill_ratio_offset=0.0,
        )

        baseline_fill_ratio = processor_v1._measure_template_baseline_fill_ratio(template, params)
        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=baseline_fill_ratio)

        expected_scan_fill_ratio = processor_v1._measure_ellipse_fill_ratio(image)
        assert result["fill_ratio"] == pytest.approx(expected_scan_fill_ratio)
        assert result["baseline_fill_ratio"] == pytest.approx(baseline_fill_ratio)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(baseline_fill_ratio)
        assert result["delta_fill_ratio"] == pytest.approx(expected_scan_fill_ratio - baseline_fill_ratio)

    def test_rect_mode_uses_same_rect_basis_for_scan_and_baseline(self, processor_v1):
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[:, :20] = 0
        image = template.copy()
        image[:, 20:50] = 0
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            baseline_fill_ratio_offset=0.0,
            bubble_measurement_shape="rect",
        )

        baseline_fill_ratio = processor_v1._measure_template_baseline_fill_ratio(template, params)
        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=baseline_fill_ratio)

        expected_scan_fill_ratio = processor_v1._measure_rect_fill_ratio(image, params)
        assert result["fill_ratio"] == pytest.approx(expected_scan_fill_ratio)
        assert result["baseline_fill_ratio"] == pytest.approx(baseline_fill_ratio)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(baseline_fill_ratio)
        assert result["delta_fill_ratio"] == pytest.approx(expected_scan_fill_ratio - baseline_fill_ratio)

    def test_rect_mode_applies_baseline_offset(self, processor_v1):
        image = np.full((10, 10), 255, dtype=np.uint8)
        image[:, :4] = 0
        template = np.full((10, 10), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            baseline_fill_ratio_offset=0.10,
            bubble_measurement_shape="rect",
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.20)

        assert result["fill_ratio"] == pytest.approx(0.4)
        assert result["baseline_fill_ratio"] == pytest.approx(0.20)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(0.30)
        assert result["delta_fill_ratio"] == pytest.approx(0.10)
        assert result["is_filled"] is False

    def test_rect_absolute_mode_reports_fill_without_baseline_offset(self, processor_v1):
        image = np.zeros((20, 20), dtype=np.uint8)
        template = np.full((20, 20), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            fill_ratio_threshold=0.4,
            use_template_baseline_fill_delta=False,
            bubble_measurement_shape="rect",
            baseline_fill_ratio_offset=0.10,
        )

        result = processor_v1._check_filled_area(image, template, params, baseline_fill_ratio=0.9)

        assert result["is_filled"] is True
        assert result["fill_ratio"] == pytest.approx(1.0)
        assert result["baseline_fill_ratio"] == pytest.approx(0.0)
        assert result["adjusted_baseline_fill_ratio"] == pytest.approx(0.0)
        assert result["delta_fill_ratio"] == pytest.approx(1.0)

    def test_rect_scanned_fill_ratio_excludes_template_ink(self, processor_v1):
        image = np.full((10, 10), 255, dtype=np.uint8)
        template = np.full((10, 10), 255, dtype=np.uint8)
        template[:, :2] = 0
        image[:, :5] = 0
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=False,
            bubble_measurement_shape="rect",
        )

        fill_ratio = processor_v1._measure_scanned_rect_fill_ratio(image, template, params)

        assert fill_ratio == pytest.approx(3 / 8)

    def test_rect_scanned_fill_ratio_returns_zero_when_template_covers_entire_roi(self, processor_v1):
        image = np.zeros((10, 10), dtype=np.uint8)
        template = np.zeros((10, 10), dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=False,
            bubble_measurement_shape="rect",
        )

        fill_ratio = processor_v1._measure_scanned_rect_fill_ratio(image, template, params)

        assert fill_ratio == pytest.approx(0.0)

    def test_rect_mode_can_morphologically_remove_thin_border_noise(self, processor_v1):
        image = np.full((9, 9), 255, dtype=np.uint8)
        image[:, 0] = 0
        image[:, -1] = 0
        template = np.full((9, 9), 255, dtype=np.uint8)
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            bubble_measurement_shape="rect",
            baseline_fill_ratio_offset=0.0,
            bubble_roi_use_morphology=True,
            bubble_roi_morph_close_first=True,
            bubble_roi_morph_open_ksize=3,
        )

        fill_ratio = processor_v1._measure_rect_fill_ratio(image, params)
        baseline_fill_ratio = processor_v1._measure_template_baseline_fill_ratio(template, params)

        assert fill_ratio == pytest.approx(0.0)
        assert baseline_fill_ratio == pytest.approx(0.0)

    def test_rect_mode_roi_morphology_order_is_independent_from_document_morphology(self, processor_v1):
        image = np.full((9, 9), 255, dtype=np.uint8)
        image[4, 1:8] = 0
        params = ImageProcessingParams(
            bubble_measurement_shape="rect",
            bubble_roi_use_morphology=True,
            bubble_roi_morph_close_first=False,
            bubble_roi_morph_open_ksize=3,
            bubble_roi_morph_close_ksize=3,
            morph_close_first=True,
        )

        fill_ratio = processor_v1._measure_rect_fill_ratio(image, params)
        assert 0.0 <= fill_ratio <= 1.0


class TestTemplateBaselineMeasurement:
    def test_counts_template_ink_inside_ellipse(self, processor_v1):
        template = np.full((100, 100), 255, dtype=np.uint8)
        template[25:75, :] = 0

        params = ImageProcessingParams(bubble_measurement_shape="ellipse")
        result = processor_v1._measure_template_baseline_fill_ratio(template, params)

        assert 0.60 < result < 0.65

    def test_zero_height_image_returns_zero(self, processor_v1):
        """Covers the shape[0]==0 / shape[1]==0 early-return in _measure_ellipse_fill_ratio."""
        empty_row = np.zeros((0, 10), dtype=np.uint8)
        empty_col = np.zeros((10, 0), dtype=np.uint8)
        params = ImageProcessingParams(bubble_measurement_shape="ellipse")
        assert processor_v1._measure_template_baseline_fill_ratio(empty_row, params) == 0.0
        assert processor_v1._measure_template_baseline_fill_ratio(empty_col, params) == 0.0

    def test_image_with_empty_ellipse_mask_returns_zero(self, processor_v1):
        """A 1x1 region produces an empty ellipse mask under the strict-inside rule;
        covers the ellipse_area==0 branch in _measure_ellipse_fill_ratio."""
        tiny = np.zeros((1, 1), dtype=np.uint8)  # value irrelevant once mask is empty
        params = ImageProcessingParams(bubble_measurement_shape="ellipse")
        assert processor_v1._measure_template_baseline_fill_ratio(tiny, params) == 0.0


class TestMeasureScannedFillRatio:
    def test_empty_ellipse_mask_returns_zero(self, processor_v1):
        """Covers the countNonZero(mask)==0 branch in _measure_scanned_fill_ratio."""
        image = np.zeros((1, 1), dtype=np.uint8)
        template = np.full((1, 1), 255, dtype=np.uint8)
        assert processor_v1._measure_scanned_fill_ratio(image, template) == 0.0


class TestBubbleEllipseMask:
    def test_excludes_corner_and_boundary_pixels(self, processor_v1):
        """A 4x4 mask should include only the central 2x2 — corner and
        boundary pixels are excluded by the strict-inside rule."""
        mask = processor_v1._bubble_ellipse_mask(4, 4)
        expected = np.array(
            [
                [0, 0, 0, 0],
                [0, 255, 255, 0],
                [0, 255, 255, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.uint8,
        )
        np.testing.assert_array_equal(mask, expected)

    def test_zero_dims(self, processor_v1):
        assert processor_v1._bubble_ellipse_mask(0, 10).size == 0
        assert processor_v1._bubble_ellipse_mask(10, 0).size == 0

    def test_strict_excludes_boundary_for_large_mask(self, processor_v1):
        """Pixels touching the ellipse boundary must be excluded; pixels in
        the strict interior must be included. Spot-check a 100x100 mask."""
        mask = processor_v1._bubble_ellipse_mask(100, 100)
        # Center pixel sits well inside the ellipse.
        assert mask[50, 50] == 255
        # Bbox corner sits well outside.
        assert mask[0, 0] == 0
        # The pixel at (0, 50) lies on the ellipse boundary (top-most row);
        # under strict-inside it must be excluded.
        assert mask[0, 50] == 0


class TestBubbleCropBounds:
    def test_default_ratio_preserves_original_bbox(self, processor_v1):
        child_pos = {"x": 10.0, "y": 20.0, "width": 8.0, "height": 6.0}
        bounds = processor_v1._bubble_crop_bounds(
            area_pos_x=100.0, area_pos_y=200.0, child_pos=child_pos,
            padding_ratio=1.0, scale=1.0,
        )
        assert bounds == (110, 220, 8, 6)

    def test_ratio_keeps_center_when_shrinking(self, processor_v1):
        child_pos = {"x": 10.0, "y": 20.0, "width": 10.0, "height": 10.0}
        # Original bubble center = (115, 225). Shrinking by 0.5 → 5x5 crop
        # still centered at (115, 225) ⇒ top-left (112.5, 222.5).
        bounds = processor_v1._bubble_crop_bounds(
            area_pos_x=100.0, area_pos_y=200.0, child_pos=child_pos,
            padding_ratio=0.5, scale=1.0,
        )
        pos_x_px, pos_y_px, width_px, height_px = bounds
        assert width_px == 5
        assert height_px == 5
        # Center of new crop matches original bubble center within rounding.
        new_cx = pos_x_px + width_px / 2.0
        new_cy = pos_y_px + height_px / 2.0
        assert new_cx == pytest.approx(115.0, abs=0.5)
        assert new_cy == pytest.approx(225.0, abs=0.5)

    def test_ratio_keeps_center_when_expanding(self, processor_v1):
        child_pos = {"x": 10.0, "y": 20.0, "width": 10.0, "height": 10.0}
        bounds = processor_v1._bubble_crop_bounds(
            area_pos_x=100.0, area_pos_y=200.0, child_pos=child_pos,
            padding_ratio=1.5, scale=1.0,
        )
        pos_x_px, pos_y_px, width_px, height_px = bounds
        assert width_px == 15
        assert height_px == 15
        new_cx = pos_x_px + width_px / 2.0
        new_cy = pos_y_px + height_px / 2.0
        assert new_cx == pytest.approx(115.0, abs=0.5)
        assert new_cy == pytest.approx(225.0, abs=0.5)


class TestOddAtLeast:
    def test_already_odd(self, processor_v1):
        assert processor_v1._odd_at_least(5) == 5

    def test_even_becomes_odd(self, processor_v1):
        assert processor_v1._odd_at_least(4) == 5

    def test_below_minimum(self, processor_v1):
        assert processor_v1._odd_at_least(1) == 3

    def test_custom_minimum(self, processor_v1):
        assert processor_v1._odd_at_least(1, at_least=7) == 7

    def test_large_value(self, processor_v1):
        assert processor_v1._odd_at_least(100) == 101
        assert processor_v1._odd_at_least(101) == 101


class TestBinarizeDocument:
    def test_rgb_input(self, processor_v1):
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        params = ImageProcessingParams()
        result = processor_v1._binarize_document(image, params)
        assert result.shape == (100, 100)
        assert result.dtype == np.uint8

    def test_grayscale_input(self, processor_v1):
        image = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        params = ImageProcessingParams()
        result = processor_v1._binarize_document(image, params)
        assert result.shape == (100, 100)

    def test_output_is_binary(self, processor_v1):
        image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        params = ImageProcessingParams()
        result = processor_v1._binarize_document(image, params)
        unique_values = np.unique(result)
        assert all(v in [0, 255] for v in unique_values)

    def test_no_post_thresh(self, processor_v1):
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        params = ImageProcessingParams(post_thresh_ksize=0)
        result = processor_v1._binarize_document(image, params)
        assert result.shape == (100, 100)

    def test_with_scaled_morphology(self, processor_v1):
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        params = ImageProcessingParams(
            morph_close_ksize=5,
            morph_open_ksize=3,
            reference_template_width=200,
            min_morph_kernel_size=1,
        )
        result = processor_v1._binarize_document(image, params)
        assert result.shape == (100, 100)

    def test_morph_close_first_false_uses_open_then_close(self, processor_v1):
        """Covers the morph_close_first=False branch in _binarize_document."""
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        params = ImageProcessingParams(
            morph_close_ksize=3,
            morph_open_ksize=3,
            morph_close_first=False,
        )

        with patch("worker.processors.v1.cv2.morphologyEx", wraps=cv2.morphologyEx) as morph_spy:
            processor_v1._binarize_document(image, params)

        morph_op_args = [call.args[1] for call in morph_spy.call_args_list]
        # First op must be OPEN, then CLOSE — the False branch ordering.
        assert morph_op_args[0] == cv2.MORPH_OPEN
        assert morph_op_args[1] == cv2.MORPH_CLOSE


class TestDecideIsFilled:
    def test_absolute_threshold_clamps_delta_filled_bubble_to_unfilled(self, processor_v1):
        """Covers the `absolute_fill_ratio_threshold is not None` branch in _decide_is_filled."""
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.1,
            absolute_fill_ratio_threshold=0.9,
        )
        # Delta of 0.5 - 0.1 = 0.4 clears the delta threshold, but fill_ratio 0.5
        # falls below the absolute threshold of 0.9, so the AND clamp flips to False.
        is_filled, delta = processor_v1._decide_is_filled(
            fill_ratio=0.5, baseline_fill_ratio=0.1, params=params,
        )
        assert is_filled is False
        assert delta == pytest.approx(0.4)

    def test_absolute_threshold_allows_filled_when_fill_ratio_high(self, processor_v1):
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.1,
            absolute_fill_ratio_threshold=0.5,
        )
        is_filled, _ = processor_v1._decide_is_filled(
            fill_ratio=0.95, baseline_fill_ratio=0.1, params=params,
        )
        assert is_filled is True


class TestRecognitionResizeHelpers:
    def test_resize_for_recognition_scales_down(self, processor_v1):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        resized, scale = processor_v1._resize_for_recognition(image, 100)
        assert resized.shape[:2] == (50, 100)
        assert scale == pytest.approx(0.5)

    def test_resize_for_recognition_uses_explicit_scale(self, processor_v1):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        resized, scale = processor_v1._resize_for_recognition(image, 100, explicit_scale=0.25)
        assert resized.shape[:2] == (25, 50)
        assert scale == pytest.approx(0.25)

    def test_scaled_kernel_size_uses_reference_width(self, processor_v1):
        params = ImageProcessingParams(reference_template_width=200, adaptive_kernel_scaling=True, min_morph_kernel_size=1)
        assert processor_v1._scaled_kernel_size(5, 100, params) == 3


def _stub_exam_paper(paper_id, *, background_image: str = "bg.png"):
    import datetime as dt
    paper = MagicMock()
    paper.id = paper_id
    paper.background_image = background_image
    paper.updated_at = dt.datetime(2026, 5, 1, 12, 0, 0)
    return paper


def _stub_exam(exam_id):
    import datetime as dt
    exam = MagicMock()
    exam.id = exam_id
    exam.updated_at = dt.datetime(2026, 5, 2, 12, 0, 0)
    return exam


def _stub_exam_round(round_id=None):
    import datetime as dt
    import uuid as uuid_mod
    exam_round = MagicMock()
    exam_round.id = round_id or uuid_mod.uuid4()
    exam_round.updated_at = dt.datetime(2026, 5, 3, 12, 0, 0)
    return exam_round


class TestGetOrBinarizeTemplate:
    """Cache I/O failures must degrade to miss/no-op, not abort processing."""

    async def test_cache_read_failure_falls_back_to_binarize(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        exam_paper = _stub_exam_paper(uuid_mod.uuid4())
        exam = _stub_exam(uuid_mod.uuid4())
        template = np.full((50, 50, 3), 255, dtype=np.uint8)
        params = ImageProcessingParams()

        with (
            patch("worker.processors.v1.cache.get_template_thresh",
                  side_effect=OSError("simulated read failure")),
            patch("worker.processors.v1.cache.put_template_thresh") as put_mock,
        ):
            result = await processor_v1._get_or_binarize_template(
                exam_paper, exam, _stub_exam_round(), template, params,
            )

        assert result.shape == (50, 50)
        assert result.dtype == np.uint8
        put_mock.assert_called_once()
        warn_args = [c.args[0] for c in processor_v1._logger.warn.call_args_list]
        assert any("cache read failed" in m for m in warn_args)

    async def test_cache_write_failure_is_swallowed(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        exam_paper = _stub_exam_paper(uuid_mod.uuid4())
        exam = _stub_exam(uuid_mod.uuid4())
        template = np.full((50, 50, 3), 255, dtype=np.uint8)
        params = ImageProcessingParams()

        with (
            patch("worker.processors.v1.cache.get_template_thresh", return_value=None),
            patch("worker.processors.v1.cache.put_template_thresh",
                  side_effect=OSError("simulated write failure")),
        ):
            result = await processor_v1._get_or_binarize_template(
                exam_paper, exam, _stub_exam_round(), template, params,
            )

        assert result.shape == (50, 50)
        warn_args = [c.args[0] for c in processor_v1._logger.warn.call_args_list]
        assert any("cache write failed" in m for m in warn_args)

    async def test_cache_hit_returns_cached_without_binarizing(self, processor_v1):
        """Positive branch: a hit must skip _binarize_document and the put_* call."""
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        exam_paper = _stub_exam_paper(uuid_mod.uuid4())
        exam = _stub_exam(uuid_mod.uuid4())
        template = np.full((50, 50, 3), 255, dtype=np.uint8)
        cached = np.full((50, 50), 128, dtype=np.uint8)
        params = ImageProcessingParams()

        with (
            patch("worker.processors.v1.cache.get_template_thresh", return_value=cached),
            patch("worker.processors.v1.cache.put_template_thresh") as put_mock,
            patch.object(processor_v1, "_binarize_document") as binarize_mock,
        ):
            result = await processor_v1._get_or_binarize_template(
                exam_paper, exam, _stub_exam_round(), template, params,
            )

        np.testing.assert_array_equal(result, cached)
        binarize_mock.assert_not_called()
        put_mock.assert_not_called()
        info_args = [c.args[0] for c in processor_v1._logger.info.call_args_list]
        assert any("cache hit" in m for m in info_args)

    async def test_cacheable_false_bypasses_read_and_write(self, processor_v1):
        """cacheable=False must skip both cache.get_* and cache.put_*. The
        caller uses it when the input template is known-incomplete (e.g.
        TEXT rendering hit a transient error) so neither a stale cached
        entry is served nor a partial one is written back."""
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        exam_paper = _stub_exam_paper(uuid_mod.uuid4())
        exam = _stub_exam(uuid_mod.uuid4())
        template = np.full((50, 50, 3), 255, dtype=np.uint8)
        params = ImageProcessingParams()

        with (
            patch("worker.processors.v1.cache.get_template_thresh") as get_mock,
            patch("worker.processors.v1.cache.put_template_thresh") as put_mock,
        ):
            result = await processor_v1._get_or_binarize_template(
                exam_paper, exam, _stub_exam_round(), template, params, cacheable=False,
            )

        assert result.shape == (50, 50)
        get_mock.assert_not_called()
        put_mock.assert_not_called()


class TestGetOrComputeTemplateBaselineFillMap:
    async def test_cacheable_false_bypasses_read_and_write(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        computed_map = {"area-a:1": 0.25}

        with (
            patch("worker.processors.v1.cache.get_template_baseline_fill_map") as get_mock,
            patch("worker.processors.v1.cache.put_template_baseline_fill_map") as put_mock,
            patch.object(
                processor_v1, "_compute_template_baseline_fill_map", return_value=computed_map
            ) as compute_mock,
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [],
                ImageProcessingParams(),
                cacheable=False,
            )

        assert result == computed_map
        compute_mock.assert_called_once()
        get_mock.assert_not_called()
        put_mock.assert_not_called()

    async def test_cache_hit_reuses_baseline_map(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        cached_map = {"area-a:1": 0.25}
        area = MagicMock()

        with (
            patch("worker.processors.v1.cache.get_template_baseline_fill_map", return_value=cached_map),
            patch.object(processor_v1, "_compute_template_baseline_fill_map") as compute_mock,
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [area],
                ImageProcessingParams(),
            )

        assert result == cached_map
        compute_mock.assert_not_called()

    async def test_cache_miss_computes_and_stores_baseline_map(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        computed_map = {"area-a:1": 0.25}

        with (
            patch("worker.processors.v1.cache.get_template_baseline_fill_map", return_value=None),
            patch("worker.processors.v1.cache.put_template_baseline_fill_map") as put_mock,
            patch.object(processor_v1, "_compute_template_baseline_fill_map", return_value=computed_map) as compute_mock,
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [],
                ImageProcessingParams(),
            )

        assert result == computed_map
        compute_mock.assert_called_once()
        put_mock.assert_called_once()

    async def test_corrupt_baseline_cache_json_degrades_to_miss(self, processor_v1):
        import json as json_mod
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        computed_map = {"area-a:1": 0.25}

        with (
            patch(
                "worker.processors.v1.cache.get_template_baseline_fill_map",
                side_effect=json_mod.JSONDecodeError("Expecting value", "doc", 0),
            ),
            patch("worker.processors.v1.cache.put_template_baseline_fill_map"),
            patch.object(processor_v1, "_compute_template_baseline_fill_map", return_value=computed_map) as compute_mock,
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [],
                ImageProcessingParams(),
            )

        assert result == computed_map
        compute_mock.assert_called_once()
        warn_args = [c.args[0] for c in processor_v1._logger.warn.call_args_list]
        assert any("cache read failed" in m for m in warn_args)

    async def test_oserror_on_baseline_cache_read_degrades_to_miss(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        computed_map = {"area-a:1": 0.25}

        with (
            patch(
                "worker.processors.v1.cache.get_template_baseline_fill_map",
                side_effect=OSError("simulated read failure"),
            ),
            patch("worker.processors.v1.cache.put_template_baseline_fill_map") as put_mock,
            patch.object(processor_v1, "_compute_template_baseline_fill_map", return_value=computed_map) as compute_mock,
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [],
                ImageProcessingParams(),
            )

        assert result == computed_map
        compute_mock.assert_called_once()
        put_mock.assert_called_once()
        warn_args = [c.args[0] for c in processor_v1._logger.warn.call_args_list]
        assert any("cache read failed" in m for m in warn_args)

    async def test_oserror_on_baseline_cache_write_is_swallowed(self, processor_v1):
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()
        computed_map = {"area-a:1": 0.25}

        with (
            patch("worker.processors.v1.cache.get_template_baseline_fill_map", return_value=None),
            patch(
                "worker.processors.v1.cache.put_template_baseline_fill_map",
                side_effect=OSError("simulated write failure"),
            ),
            patch.object(processor_v1, "_compute_template_baseline_fill_map", return_value=computed_map),
        ):
            result = await processor_v1._get_or_compute_template_baseline_fill_map(
                _stub_exam_paper(uuid_mod.uuid4()),
                _stub_exam(uuid_mod.uuid4()),
                _stub_exam_round(),
                np.full((10, 10), 255, dtype=np.uint8),
                [],
                ImageProcessingParams(),
            )

        assert result == computed_map
        warn_args = [c.args[0] for c in processor_v1._logger.warn.call_args_list]
        assert any("cache write failed" in m for m in warn_args)


class TestComputeTemplateBaselineFillMap:
    """Exercise the unmocked body of _compute_template_baseline_fill_map."""

    def _make_area(self, area_id: UUID, children: dict, pos_x: float = 0.0, pos_y: float = 0.0):
        area = MagicMock()
        area.id = area_id
        area.pos_x = pos_x
        area.pos_y = pos_y
        area.data = {"children": children}
        return area

    def test_empty_areas_returns_empty_map(self, processor_v1):
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)
        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [], ImageProcessingParams(),
        )
        assert result == {}

    def test_keys_match_baseline_fill_map_key_for_each_child(self, processor_v1):
        area_id = UUID("12345678-1234-5678-1234-567812345678")
        area = self._make_area(area_id, {
            "A": {"x": 10, "y": 10, "width": 20, "height": 20},
            "B": {"x": 40, "y": 40, "width": 20, "height": 20},
        })
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)

        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [area], ImageProcessingParams(),
        )

        assert set(result.keys()) == {f"{area_id}:A", f"{area_id}:B"}

    def test_blank_template_yields_zero_baseline(self, processor_v1):
        area_id = UUID("12345678-1234-5678-1234-567812345678")
        area = self._make_area(area_id, {
            "A": {"x": 10, "y": 10, "width": 20, "height": 20},
        })
        # All-white template => no dark pixels => baseline 0.
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)

        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [area], ImageProcessingParams(),
        )

        assert result[f"{area_id}:A"] == pytest.approx(0.0)

    def test_preprinted_template_yields_nonzero_baseline(self, processor_v1):
        """Template ink inside a bubble must register as a non-zero baseline."""
        area_id = UUID("12345678-1234-5678-1234-567812345678")
        area = self._make_area(area_id, {
            "A": {"x": 10, "y": 10, "width": 20, "height": 20},
        })
        # All-black template => every pixel inside the ellipse is "ink" => baseline ~1.0.
        template_thresh = np.zeros((100, 100), dtype=np.uint8)

        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [area], ImageProcessingParams(),
        )

        assert result[f"{area_id}:A"] == pytest.approx(1.0)

    def test_skips_children_clipped_to_zero_area(self, processor_v1):
        """Bubbles entirely outside the image bounds must be skipped, not included with stale values."""
        area_id = UUID("12345678-1234-5678-1234-567812345678")
        area = self._make_area(area_id, {
            "IN_BOUNDS": {"x": 10, "y": 10, "width": 20, "height": 20},
            "OFF_RIGHT": {"x": 200, "y": 10, "width": 20, "height": 20},
            "OFF_BOTTOM": {"x": 10, "y": 200, "width": 20, "height": 20},
        }, pos_x=0.0, pos_y=0.0)
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)

        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [area], ImageProcessingParams(),
        )

        assert set(result.keys()) == {f"{area_id}:IN_BOUNDS"}

    def test_computes_baselines_for_multiple_areas(self, processor_v1):
        area_a = self._make_area(
            UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            {"1": {"x": 10, "y": 10, "width": 20, "height": 20}},
        )
        area_b = self._make_area(
            UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            {"1": {"x": 50, "y": 50, "width": 20, "height": 20}},
        )
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)

        result = processor_v1._compute_template_baseline_fill_map(
            template_thresh, [area_a, area_b], ImageProcessingParams(),
        )

        assert set(result.keys()) == {
            f"{area_a.id}:1",
            f"{area_b.id}:1",
        }


class TestSaveOutputImages:
    def test_saves_images(self, processor_v1):
        with tempfile.TemporaryDirectory() as tmpdir:
            req_id = UUID("12345678-1234-5678-1234-567812345678")
            job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")

            thresh = np.zeros((50, 50), dtype=np.uint8)
            warped = np.zeros((50, 50, 3), dtype=np.uint8)

            with patch("worker.processors.v1.get_result_path", side_effect=[
                os.path.join(tmpdir, "threshold.png"),
                os.path.join(tmpdir, "flattened.png"),
            ]):
                thresh_path, flat_path = processor_v1._save_output_images(req_id, job_id, thresh, warped)

            assert os.path.exists(thresh_path)
            assert os.path.exists(flat_path)

    def test_threshold_imencode_failure_raises_oserror(self, processor_v1):
        """Covers the `if not threshold_ok` raise branch in _save_output_images."""
        req_id = UUID("12345678-1234-5678-1234-567812345678")
        job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        thresh = np.zeros((50, 50), dtype=np.uint8)
        warped = np.zeros((50, 50, 3), dtype=np.uint8)

        with (
            patch("worker.processors.v1.get_result_path", return_value="/tmp/unused.png"),
            patch("worker.processors.v1.cv2.imencode", return_value=(False, np.empty(0, dtype=np.uint8))),
        ):
            with pytest.raises(OSError, match="threshold image"):
                processor_v1._save_output_images(req_id, job_id, thresh, warped)

    def test_flattened_imencode_failure_raises_oserror(self, processor_v1):
        """Covers the `if not flattened_ok` raise branch in _save_output_images."""
        req_id = UUID("12345678-1234-5678-1234-567812345678")
        job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        thresh = np.zeros((50, 50), dtype=np.uint8)
        warped = np.zeros((50, 50, 3), dtype=np.uint8)
        # First call (threshold) succeeds; second call (flattened) reports failure.
        encoded = np.zeros(8, dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("worker.processors.v1.get_result_path", side_effect=[
                    os.path.join(tmpdir, "threshold.png"),
                    os.path.join(tmpdir, "flattened.png"),
                ]),
                patch(
                    "worker.processors.v1.cv2.imencode",
                    side_effect=[(True, encoded), (False, np.empty(0, dtype=np.uint8))],
                ),
            ):
                with pytest.raises(OSError, match="flattened image"):
                    processor_v1._save_output_images(req_id, job_id, thresh, warped)


class TestProcessChildAreas:
    def test_empty_areas(self, processor_v1):
        thresh = np.zeros((100, 100), dtype=np.uint8)
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)
        params = ImageProcessingParams()
        annotations, detected, paths, metrics = processor_v1._process_child_areas(
            thresh, template_thresh, [], UUID("12345678-1234-5678-1234-567812345678"),
            UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"), params
        )
        assert annotations == []
        assert detected == {}
        assert paths == {}
        assert metrics == {}

    def test_processes_children(self, processor_v1):
        """Test with a mock area that has children."""
        thresh = np.full((200, 200), 255, dtype=np.uint8)
        template_thresh = np.full((200, 200), 255, dtype=np.uint8)
        # Make some areas black (filled)
        thresh[10:30, 10:30] = 0

        area = MagicMock()
        area.id = UUID("12345678-1234-5678-1234-567812345678")
        area.index = 0
        area.pos_x = 0
        area.pos_y = 0
        area.area_type = MagicMock()
        area.area_type.base_type = Exampaperareabasetype.PROBLEM
        area.data = {
            "children": {
                "A": {"x": 10, "y": 10, "width": 20, "height": 20},  # black area (filled)
                "B": {"x": 50, "y": 50, "width": 20, "height": 20},  # white area (not filled)
            }
        }

        params = ImageProcessingParams(fill_ratio_threshold=0.4)

        with patch.object(processor_v1, "_save_area_image", return_value="/tmp/area.png"):
            annotations, detected, paths, metrics = processor_v1._process_child_areas(
                thresh, template_thresh, [area],
                UUID("12345678-1234-5678-1234-567812345678"),
                UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                params,
            )

        assert len(annotations) == 2
        assert 0 in detected
        assert "A" in detected[0]
        assert "B" not in detected[0]

    def test_skips_zero_size_region(self, processor_v1):
        """Child region outside image bounds should be skipped."""
        thresh = np.zeros((10, 10), dtype=np.uint8)
        template_thresh = np.full((10, 10), 255, dtype=np.uint8)

        area = MagicMock()
        area.id = UUID("12345678-1234-5678-1234-567812345678")
        area.index = 0
        area.pos_x = 0
        area.pos_y = 0
        area.area_type = MagicMock()
        area.area_type.base_type = Exampaperareabasetype.IDENTIFIER
        area.data = {
            "children": {
                "A": {"x": 100, "y": 100, "width": 20, "height": 20},  # Out of bounds
            }
        }

        params = ImageProcessingParams()
        annotations, detected, paths, metrics = processor_v1._process_child_areas(
            thresh, template_thresh, [area],
            UUID("12345678-1234-5678-1234-567812345678"),
            UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
            params,
        )

        assert 0 in detected
        assert detected[0] == []

    def test_scales_child_coordinates_for_low_res_reading(self, processor_v1):
        thresh = np.full((100, 100), 255, dtype=np.uint8)
        template_thresh = np.full((100, 100), 255, dtype=np.uint8)
        thresh[5:15, 5:15] = 0

        area = MagicMock()
        area.id = UUID("12345678-1234-5678-1234-567812345678")
        area.index = 0
        area.pos_x = 0
        area.pos_y = 0
        area.area_type = MagicMock()
        area.area_type.base_type = Exampaperareabasetype.PROBLEM
        area.data = {
            "children": {
                "A": {"x": 10, "y": 10, "width": 20, "height": 20},
            }
        }

        params = ImageProcessingParams(fill_ratio_threshold=0.2)
        with patch.object(processor_v1, "_save_area_image", return_value="/tmp/area.png"):
            _, detected, _, _ = processor_v1._process_child_areas(
                thresh,
                template_thresh,
                [area],
                UUID("12345678-1234-5678-1234-567812345678"),
                UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                params.model_copy(update={"recognition_scale": 0.5}),
            )

        assert detected[0] == ["A"]

    def test_delta_mode_missing_baseline_key_falls_back_to_zero(self, processor_v1):
        thresh = np.full((60, 60), 255, dtype=np.uint8)
        template_thresh = np.full((60, 60), 255, dtype=np.uint8)
        thresh[10:30, 10:30] = 0

        area = MagicMock()
        area.id = UUID("12345678-1234-5678-1234-567812345678")
        area.index = 0
        area.pos_x = 0
        area.pos_y = 0
        area.area_type = MagicMock()
        area.area_type.base_type = Exampaperareabasetype.PROBLEM
        area.data = {"children": {"A": {"x": 10, "y": 10, "width": 20, "height": 20}}}

        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            baseline_fill_ratio_offset=0.0,
        )

        with patch.object(processor_v1, "_save_area_image", return_value="/tmp/area.png"):
            _, detected, _, metrics = processor_v1._process_child_areas(
                thresh,
                template_thresh,
                [area],
                UUID("12345678-1234-5678-1234-567812345678"),
                UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                params,
                baseline_fill_map={},
            )

        metric = metrics[f"{area.id}_A"]
        assert detected[0] == ["A"]
        assert metric["baseline_fill_ratio"] == pytest.approx(0.0)
        assert metric["delta_fill_ratio"] == pytest.approx(metric["fill_ratio"])

    def test_classifier_assist_updates_ambiguous_bubble(self, processor_v1):
        thresh = np.full((60, 60), 255, dtype=np.uint8)
        template_thresh = np.full((60, 60), 255, dtype=np.uint8)
        thresh[10:30, 10:30] = 0

        area = MagicMock()
        area.id = UUID("12345678-1234-5678-1234-567812345678")
        area.index = 0
        area.pos_x = 0
        area.pos_y = 0
        area.area_type = MagicMock()
        area.area_type.base_type = Exampaperareabasetype.PROBLEM
        area.data = {"children": {"A": {"x": 10, "y": 10, "width": 20, "height": 20}}}

        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_classifier_delta_margin=0.05,
            use_bubble_classifier=True,
            bubble_classifier_model_uri="s3://bucket/models/best.pt",
            bubble_classifier_threshold=0.5,
        )
        classifier = SimpleNamespace(predict_filled_probability=lambda image: 0.9)

        with (
            patch.object(processor_v1, "_save_area_image", return_value="/tmp/area.png"),
            patch.object(
                processor_v1,
                "_check_filled_area",
                return_value={
                    "version": 1,
                    "is_filled": False,
                    "fill_ratio": 0.42,
                    "baseline_fill_ratio": 0.0,
                    "adjusted_baseline_fill_ratio": 0.0,
                    "delta_fill_ratio": 0.41,
                },
            ),
        ):
            _, detected, _, metrics = processor_v1._process_child_areas(
                thresh,
                template_thresh,
                [area],
                UUID("12345678-1234-5678-1234-567812345678"),
                UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"),
                params,
                baseline_fill_map={},
                bubble_classifier=classifier,
            )

        metric = metrics[f"{area.id}_A"]
        assert detected[0] == ["A"]
        assert metric["rule_is_filled"] is False
        assert metric["classifier_ambiguous"] is True
        assert metric["classifier_invoked"] is True
        assert metric["classifier_probability"] == pytest.approx(0.9)
        assert metric["classifier_predicted_filled"] is True
        assert metric["classifier_fallback_used"] is False
        assert metric["is_filled"] is True

    def test_classifier_assist_falls_back_when_model_missing(self, processor_v1):
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_classifier_delta_margin=0.05,
            use_bubble_classifier=True,
            bubble_classifier_model_uri="s3://bucket/models/best.pt",
        )
        metrics = {
            "version": 1,
            "is_filled": False,
            "fill_ratio": 0.42,
            "baseline_fill_ratio": 0.0,
            "adjusted_baseline_fill_ratio": 0.0,
            "delta_fill_ratio": 0.41,
        }

        result = processor_v1._apply_bubble_classifier_assist(
            area_key="area_A",
            image=np.zeros((10, 10), dtype=np.uint8),
            metrics=metrics,
            params=params,
            bubble_classifier=None,
            bubble_classifier_load_error="failed to load",
        )

        assert result["is_filled"] is False
        assert result["rule_is_filled"] is False
        assert result["classifier_ambiguous"] is True
        assert result["classifier_invoked"] is False
        assert result["classifier_fallback_used"] is True
        assert result["classifier_error"] == "failed to load"

    def test_classifier_assist_logs_and_falls_back_on_inference_error(self, processor_v1):
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_classifier_delta_margin=0.05,
            use_bubble_classifier=True,
            bubble_classifier_model_uri="s3://bucket/models/best.pt",
        )
        metrics = {
            "version": 1,
            "is_filled": True,
            "fill_ratio": 0.42,
            "baseline_fill_ratio": 0.0,
            "adjusted_baseline_fill_ratio": 0.0,
            "delta_fill_ratio": 0.41,
        }
        classifier = SimpleNamespace(
            predict_filled_probability=MagicMock(side_effect=RuntimeError("boom")),
        )

        with patch.object(processor_v1, "_schedule_warn") as schedule_warn:
            result = processor_v1._apply_bubble_classifier_assist(
                area_key="area_A",
                image=np.zeros((10, 10), dtype=np.uint8),
                metrics=metrics,
                params=params,
                bubble_classifier=classifier,
                bubble_classifier_load_error=None,
            )

        assert result["is_filled"] is True
        assert result["classifier_fallback_used"] is True
        assert "Bubble classifier inference failed" in result["classifier_error"]
        schedule_warn.assert_called_once()

    def test_classifier_assist_skips_non_ambiguous_bubbles(self, processor_v1):
        params = ImageProcessingParams(
            use_template_baseline_fill_delta=True,
            delta_fill_ratio_threshold=0.4,
            bubble_classifier_delta_margin=0.05,
            use_bubble_classifier=True,
            bubble_classifier_model_uri="s3://bucket/models/best.pt",
        )
        metrics = {
            "version": 1,
            "is_filled": False,
            "fill_ratio": 0.2,
            "baseline_fill_ratio": 0.0,
            "adjusted_baseline_fill_ratio": 0.0,
            "delta_fill_ratio": 0.1,
        }
        classifier = SimpleNamespace(predict_filled_probability=MagicMock(return_value=0.9))

        result = processor_v1._apply_bubble_classifier_assist(
            area_key="area_A",
            image=np.zeros((10, 10), dtype=np.uint8),
            metrics=metrics,
            params=params,
            bubble_classifier=classifier,
            bubble_classifier_load_error=None,
        )

        assert result["is_filled"] is False
        assert result["classifier_ambiguous"] is False
        assert result["classifier_invoked"] is False
        assert result["classifier_fallback_used"] is False
        classifier.predict_filled_probability.assert_not_called()


class TestMetadataAreaProcessing:
    """End-to-end metadata flow through ProcessorV1.process.

    Exercises the new METADATA pipeline: filtering, _process_child_areas dispatch,
    and remapping detected localIds from area.index keys into area.id keys.
    """

    async def test_metadata_area_surfaces_in_metadata_results(self, processor_v1):
        import base64
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()

        exam_round_id = uuid_mod.uuid4()
        qr_area_id = uuid_mod.uuid4()
        b64_e = base64.urlsafe_b64encode(exam_round_id.bytes).decode().rstrip("=")
        b64_a = base64.urlsafe_b64encode(qr_area_id.bytes).decode().rstrip("=")

        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a={b64_a}"
        barcode.position.top_left = MagicMock(x=10.0, y=10.0)
        barcode.position.top_right = MagicMock(x=190.0, y=10.0)
        barcode.position.bottom_right = MagicMock(x=190.0, y=190.0)
        barcode.position.bottom_left = MagicMock(x=10.0, y=190.0)

        exam = MagicMock()
        exam.id = uuid_mod.uuid4()
        exam.organization_id = uuid_mod.uuid4()
        exam.exam_paper_id = uuid_mod.uuid4()
        exam_paper = MagicMock()
        exam_paper.id = uuid_mod.uuid4()
        exam_paper.background_image = "templates/bg.png"
        paper_type = MagicMock()
        area = MagicMock()
        exam_round = MagicMock()

        qr_area = MagicMock()
        qr_area.id = qr_area_id
        qr_area.area_type = MagicMock()
        qr_area.area_type.base_type = "QRCODE"

        metadata_area_id = uuid_mod.uuid4()
        metadata_area = MagicMock()
        metadata_area.id = metadata_area_id
        metadata_area.index = 7
        metadata_area.area_type = MagicMock()

        class _MetadataBaseType:
            value = "METADATA"

            def __eq__(self, other):
                return other == "METADATA" or getattr(other, "value", None) == "METADATA"

        metadata_area.area_type.base_type = _MetadataBaseType()
        metadata_area.pos_x = 0
        metadata_area.pos_y = 0
        # A 20x20 black square inside the 200x200 binarized image at (10,10)
        # so the "A" bubble registers as filled.
        metadata_area.data = {
            "children": {
                "A": {"x": 10, "y": 10, "width": 20, "height": 20},
                "B": {"x": 60, "y": 60, "width": 20, "height": 20},
            }
        }

        # Build a binarized image with a filled bubble at A's coordinates.
        warped = np.full((200, 200, 3), 255, dtype=np.uint8)
        warped[10:30, 10:30] = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["thresh.png", "flat.png", "annotated.png"]:
                cv2.imwrite(os.path.join(tmpdir, name), np.zeros((10, 10), dtype=np.uint8))

            template = np.zeros((300, 300, 3), dtype=np.uint8)

            with (
                patch.object(processor_v1, "_detect_qrcode", return_value=(barcode, [], exam_round_id, qr_area_id)),
                patch.object(processor_v1, "_detect_all_qrcodes", return_value={qr_area_id: barcode}),
                patch.object(
                    processor_v1,
                    "_get_database_records",
                    AsyncMock(return_value=(exam_round, exam, exam_paper, paper_type, area, [qr_area, metadata_area])),
                ),
                patch("worker.processors.v1.prepare_image", AsyncMock(return_value=(template, 1.0))),
                patch("worker.processors.v1.render_qrcode_on_template", return_value=template),
                patch.object(
                    processor_v1,
                    "_align_scan_to_template",
                    AsyncMock(return_value=(warped, "romav2_dense", 0.9)),
                ),
                patch.object(
                    processor_v1,
                    "_save_output_images",
                    return_value=(os.path.join(tmpdir, "thresh.png"), os.path.join(tmpdir, "flat.png")),
                ),
                patch.object(processor_v1, "_save_area_image", return_value="/tmp/area.png"),
                patch.object(
                    processor_v1,
                    "_get_or_compute_template_baseline_fill_map",
                    AsyncMock(return_value={}),
                ),
                patch("worker.processors.v1.get_result_path", return_value=os.path.join(tmpdir, "annotated.png")),
                patch("worker.processors.v1.get_results_dir", return_value=tmpdir),
            ):
                # A is fully black inside a baseline of all-white template, so the
                # delta over baseline crosses the default threshold and registers as filled.
                image = np.zeros((200, 200, 3), dtype=np.uint8)
                result = await processor_v1.process(image, uuid_mod.uuid4(), uuid_mod.uuid4(), {})

        # Verify the new field keys by area.id (not area.index) and only contains
        # detected (filled) localIds, mirroring problem_results / option_results semantics.
        assert metadata_area_id in result["metadata_results"]
        assert result["metadata_results"][metadata_area_id] == ["A"]


class TestAlignScanToTemplate:
    @pytest.fixture
    def processor_for_align(self, processor_v1):
        processor_v1._logger = AsyncMock()
        return processor_v1

    async def test_initializes_matcher_if_needed(self, processor_for_align):
        """When matcher has not been warmed up, alignment initializes it before matching."""
        processor_for_align._matcher._initialized = False
        processor_for_align._matcher.initialize.return_value = True

        match_result = MagicMock()
        match_result.confidence = 0.8
        warped_image = np.zeros((300, 300, 3), dtype=np.uint8)
        processor_for_align._matcher.warp_scan_to_template.return_value = (warped_image, match_result)

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        warped, method, confidence = await processor_for_align._align_scan_to_template(scan, template)

        processor_for_align._matcher.initialize.assert_called_once_with()
        assert method == "romav2_dense"
        assert confidence == 0.8
        assert warped is warped_image

    async def test_initialize_failure_raises(self, processor_for_align):
        """When RoMaV2 initialization fails, alignment raises instead of falling back."""
        processor_for_align._matcher._initialized = False
        processor_for_align._matcher.initialize.return_value = False

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        with pytest.raises(ProcessError) as exc_info:
            await processor_for_align._align_scan_to_template(scan, template)

        assert exc_info.value.code == "ROMAV2_INITIALIZATION_FAILED"

    async def test_romav2_low_confidence_raises(self, processor_for_align):
        """When RoMaV2 returns low confidence, alignment raises instead of falling back."""
        processor_for_align._matcher._initialized = True

        match_result = MagicMock()
        match_result.confidence = 0.1  # Below 0.3 threshold

        processor_for_align._matcher.warp_scan_to_template.return_value = (
            np.zeros((300, 300, 3), dtype=np.uint8),
            match_result,
        )

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        with pytest.raises(ProcessError) as exc_info:
            await processor_for_align._align_scan_to_template(scan, template)

        assert exc_info.value.code == "ROMAV2_LOW_CONFIDENCE"

    @pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf")])
    async def test_romav2_non_finite_confidence_raises(self, processor_for_align, confidence):
        """When RoMaV2 returns non-finite confidence, alignment raises instead of accepting the warp."""
        processor_for_align._matcher._initialized = True

        match_result = MagicMock()
        match_result.confidence = confidence

        processor_for_align._matcher.warp_scan_to_template.return_value = (
            np.zeros((300, 300, 3), dtype=np.uint8),
            match_result,
        )

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        with pytest.raises(ProcessError) as exc_info:
            await processor_for_align._align_scan_to_template(scan, template)

        assert exc_info.value.code == "ROMAV2_NON_FINITE_CONFIDENCE"

    async def test_romav2_available_high_confidence(self, processor_for_align):
        """When RoMaV2 returns high confidence, use dense warp."""
        processor_for_align._matcher._initialized = True

        match_result = MagicMock()
        match_result.confidence = 0.8

        warped_image = np.zeros((300, 300, 3), dtype=np.uint8)
        processor_for_align._matcher.warp_scan_to_template.return_value = (warped_image, match_result)

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        warped, method, confidence = await processor_for_align._align_scan_to_template(scan, template)
        assert method == "romav2_dense"
        assert confidence == 0.8

    async def test_romav2_returns_none(self, processor_for_align):
        """When RoMaV2 warp returns None, alignment raises instead of falling back."""
        processor_for_align._matcher._initialized = True
        processor_for_align._matcher.warp_scan_to_template.return_value = None

        scan = np.zeros((200, 200, 3), dtype=np.uint8)
        template = np.zeros((300, 300, 3), dtype=np.uint8)

        with pytest.raises(ProcessError) as exc_info:
            await processor_for_align._align_scan_to_template(scan, template)

        assert exc_info.value.code == "ROMAV2_ALIGNMENT_FAILED"


class TestProcessV1Process:
    """Test the full process() pipeline with mocked dependencies."""

    async def test_process_pipeline(self, processor_v1):
        import base64
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()

        # Mock QR detection
        exam_round_id = uuid_mod.uuid4()
        area_id = uuid_mod.uuid4()
        b64_e = base64.urlsafe_b64encode(exam_round_id.bytes).decode().rstrip("=")
        b64_a = base64.urlsafe_b64encode(area_id.bytes).decode().rstrip("=")

        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a={b64_a}"
        barcode.position.top_left = MagicMock(x=10.0, y=10.0)
        barcode.position.top_right = MagicMock(x=190.0, y=10.0)
        barcode.position.bottom_right = MagicMock(x=190.0, y=190.0)
        barcode.position.bottom_left = MagicMock(x=10.0, y=190.0)

        # Mock database records
        org_id = uuid_mod.uuid4()
        exam = MagicMock()
        exam.id = uuid_mod.uuid4()
        exam.organization_id = org_id
        exam.exam_paper_id = uuid_mod.uuid4()

        exam_paper = MagicMock()
        exam_paper.id = uuid_mod.uuid4()
        exam_paper.background_image = "templates/bg.png"

        paper_type = MagicMock()
        area = MagicMock()

        # Create mock areas (one QRCODE, one PROBLEM, one IDENTIFIER)
        qr_area = MagicMock()
        qr_area.id = area_id
        qr_area.area_type = MagicMock()
        qr_area.area_type.base_type = "QRCODE"
        qr_area.pos_x = 10
        qr_area.pos_y = 10
        qr_area.width = 50
        qr_area.height = 50

        problem_area = MagicMock()
        problem_area.id = uuid_mod.uuid4()
        problem_area.index = 0
        problem_area.area_type = MagicMock()
        problem_area.area_type.base_type = "PROBLEM"
        problem_area.pos_x = 0
        problem_area.pos_y = 0
        problem_area.data = {"children": {}}

        identifier_area = MagicMock()
        identifier_area.id = uuid_mod.uuid4()
        identifier_area.index = 0
        identifier_area.area_type = MagicMock()
        identifier_area.area_type.base_type = "IDENTIFIER"
        identifier_area.pos_x = 0
        identifier_area.pos_y = 0
        identifier_area.data = {"children": {}}

        areas = [qr_area, problem_area, identifier_area]
        exam_round = MagicMock()

        # Setup mocks
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mock template image
            template = np.zeros((300, 300, 3), dtype=np.uint8)

            with (
                patch.object(processor_v1, "_detect_qrcode", return_value=(
                    barcode,
                    [{"data": np.array([[10, 10], [190, 10], [190, 190], [10, 190]], dtype=np.int32), "type": "qrcode_detected", "value": barcode.text}],
                    exam_round_id,
                    area_id,
                )),
                patch.object(processor_v1, "_detect_all_qrcodes", return_value={area_id: barcode}),
                patch.object(processor_v1, "_get_database_records", AsyncMock(return_value=(exam_round, exam, exam_paper, paper_type, area, areas))),
                patch("worker.processors.v1.prepare_image", AsyncMock(return_value=(template, 1.0))),
                patch("worker.processors.v1.render_qrcode_on_template", return_value=template),
                patch.object(processor_v1, "_align_scan_to_template", AsyncMock(return_value=(
                    np.zeros((200, 200, 3), dtype=np.uint8), "romav2_dense", 0.8
                ))),
                patch.object(processor_v1, "_save_output_images", return_value=(
                    os.path.join(tmpdir, "thresh.png"), os.path.join(tmpdir, "flat.png")
                )),
                patch("worker.processors.v1.get_result_path", return_value=os.path.join(tmpdir, "annotated.png")),
                patch("worker.processors.v1.get_results_dir", return_value=tmpdir),
            ):
                # Create the files that would normally be saved
                for name in ["thresh.png", "flat.png", "annotated.png"]:
                    cv2.imwrite(os.path.join(tmpdir, name), np.zeros((10, 10), dtype=np.uint8))

                image = np.zeros((200, 200, 3), dtype=np.uint8)
                job_id = uuid_mod.uuid4()
                request_id = uuid_mod.uuid4()

                result = await processor_v1.process(image, job_id, request_id, {})

                assert result["organization_id"] == org_id
                assert result["exam_round_id"] == exam_round_id
                assert "annotations" in result
                assert result["annotations_cropped"] == []
                assert "processing_params" in result
                # METADATA areas were excluded from this fixture, so the field exists
                # but is empty. Presence ensures the key is always set so scan.py's
                # `.get("metadata_results", {})` lookup is the only safety net for
                # callers running against older ProcessResult shapes.
                assert result["metadata_results"] == {}

    async def test_template_task_cancelled_on_alignment_error(self, processor_v1):
        """If alignment raises before the binarization gather, the background
        template-binarization task must be cancelled so it doesn't outlive the job."""
        import asyncio
        import base64
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()

        exam_round_id = uuid_mod.uuid4()
        area_id = uuid_mod.uuid4()
        b64_e = base64.urlsafe_b64encode(exam_round_id.bytes).decode().rstrip("=")
        b64_a = base64.urlsafe_b64encode(area_id.bytes).decode().rstrip("=")

        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a={b64_a}"
        barcode.position.top_left = MagicMock(x=10.0, y=10.0)
        barcode.position.top_right = MagicMock(x=190.0, y=10.0)
        barcode.position.bottom_right = MagicMock(x=190.0, y=190.0)
        barcode.position.bottom_left = MagicMock(x=10.0, y=190.0)

        exam = MagicMock()
        exam.id = uuid_mod.uuid4()
        exam.organization_id = uuid_mod.uuid4()
        exam_paper = MagicMock()
        exam_paper.id = uuid_mod.uuid4()
        exam_paper.background_image = "templates/bg.png"
        paper_type = MagicMock()
        area = MagicMock()
        exam_round = MagicMock()

        template = np.zeros((50, 50, 3), dtype=np.uint8)
        cancelled = asyncio.Event()

        async def slow_binarize(*_args, **_kwargs):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return np.zeros((50, 50), dtype=np.uint8)

        async def failing_align(*_args, **_kwargs):
            # Yield once so the background template_thresh_task starts running
            # before we raise; otherwise the task never gets a turn on the loop.
            await asyncio.sleep(0)
            raise ProcessError("bad align", code="ROMAV2_ALIGNMENT_FAILED")

        with (
            patch.object(processor_v1, "_detect_qrcode", return_value=(
                barcode, [], exam_round_id, area_id,
            )),
            patch.object(processor_v1, "_detect_all_qrcodes", return_value={}),
            patch.object(processor_v1, "_get_database_records",
                         AsyncMock(return_value=(exam_round, exam, exam_paper, paper_type, area, []))),
            patch("worker.processors.v1.prepare_image", AsyncMock(return_value=(template, 1.0))),
            patch.object(processor_v1, "_get_or_binarize_template", new=slow_binarize),
            patch.object(processor_v1, "_align_scan_to_template", new=failing_align),
        ):
            image = np.zeros((200, 200, 3), dtype=np.uint8)
            with pytest.raises(ProcessError) as exc_info:
                await processor_v1.process(image, uuid_mod.uuid4(), uuid_mod.uuid4(), {})

        assert exc_info.value.code == "ROMAV2_ALIGNMENT_FAILED"
        assert cancelled.is_set(), "template_thresh_task should be cancelled on alignment error"

    async def test_process_propagates_external_cancellation(self, processor_v1):
        """If process() is cancelled from outside (shutdown/timeout) while it's
        running, CancelledError must propagate instead of being swallowed by
        the drain-task except handler in the finally block."""
        import asyncio
        import base64
        import uuid as uuid_mod

        processor_v1._logger = AsyncMock()

        exam_round_id = uuid_mod.uuid4()
        area_id = uuid_mod.uuid4()
        b64_e = base64.urlsafe_b64encode(exam_round_id.bytes).decode().rstrip("=")
        b64_a = base64.urlsafe_b64encode(area_id.bytes).decode().rstrip("=")

        barcode = MagicMock()
        barcode.text = f"https://example.com?e={b64_e}&a={b64_a}"

        exam = MagicMock()
        exam.id = uuid_mod.uuid4()
        exam.organization_id = uuid_mod.uuid4()
        exam_paper = MagicMock()
        exam_paper.id = uuid_mod.uuid4()
        exam_paper.background_image = "templates/bg.png"
        paper_type = MagicMock()
        area = MagicMock()
        exam_round = MagicMock()

        template = np.zeros((50, 50, 3), dtype=np.uint8)
        alignment_reached = asyncio.Event()

        async def slow_binarize(*_args, **_kwargs):
            await asyncio.sleep(10)
            return np.zeros((50, 50), dtype=np.uint8)

        async def stuck_align(*_args, **_kwargs):
            alignment_reached.set()
            await asyncio.sleep(10)
            return np.zeros((50, 50, 3), dtype=np.uint8), "romav2_dense", 0.9

        with (
            patch.object(processor_v1, "_detect_qrcode", return_value=(
                barcode, [], exam_round_id, area_id,
            )),
            patch.object(processor_v1, "_detect_all_qrcodes", return_value={}),
            patch.object(processor_v1, "_get_database_records",
                         AsyncMock(return_value=(exam_round, exam, exam_paper, paper_type, area, []))),
            patch("worker.processors.v1.prepare_image", AsyncMock(return_value=(template, 1.0))),
            patch.object(processor_v1, "_get_or_binarize_template", new=slow_binarize),
            patch.object(processor_v1, "_align_scan_to_template", new=stuck_align),
        ):
            process_task = asyncio.create_task(
                processor_v1.process(
                    np.zeros((200, 200, 3), dtype=np.uint8),
                    uuid_mod.uuid4(),
                    uuid_mod.uuid4(),
                    {},
                )
            )
            await alignment_reached.wait()
            process_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await process_task
