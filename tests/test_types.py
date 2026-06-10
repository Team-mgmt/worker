"""Tests for worker.types module."""

import pytest
from pydantic import ValidationError

from worker.types import ImageProcessingParams, ProcessError


class TestProcessError:
    def test_basic_error(self):
        err = ProcessError("test error")
        assert str(err) == "test error"
        assert err.message == "test error"
        assert err.code is None
        assert err.params is None

    def test_error_with_code(self):
        err = ProcessError("not found", code="NOT_FOUND")
        assert err.message == "not found"
        assert err.code == "NOT_FOUND"
        assert err.params is None

    def test_error_with_params(self):
        err = ProcessError("bad", code="BAD", params={"key": "val"})
        assert err.params == {"key": "val"}

    def test_is_exception(self):
        with pytest.raises(ProcessError):
            raise ProcessError("boom", code="BOOM")


class TestImageProcessingParams:
    def test_defaults(self):
        params = ImageProcessingParams()
        assert params.recognition_scale == 1.0
        assert params.recognition_max_width == 4000
        assert params.reference_template_width == 2480
        assert params.svg_min_render_width == 4800
        assert params.adaptive_kernel_scaling is True
        assert params.morph_close_first is True
        assert params.min_morph_kernel_size == 1
        assert params.denoise_ksize == 5
        assert params.adaptive_block_ratio == 0.02
        assert params.adaptive_block_min == 31
        assert params.adaptive_c == 7
        assert params.post_thresh_ksize == 3
        assert params.morph_open_ksize == 0
        assert params.morph_close_ksize == 0
        assert params.fill_ratio_threshold == 0.4
        assert params.use_template_baseline_fill_delta is True
        assert params.delta_fill_ratio_threshold == 0.18
        assert params.absolute_fill_ratio_threshold is None
        assert params.baseline_fill_ratio_offset == 0
        assert params.use_bubble_classifier is False
        assert params.bubble_classifier_model_uri is None
        assert params.bubble_classifier_threshold == 0.5
        assert params.bubble_classifier_delta_margin == 0.05
        assert params.bubble_measurement_shape == "rect"
        assert params.bubble_roi_use_morphology is False
        assert params.bubble_roi_morph_close_first is True
        assert params.bubble_roi_morph_open_ksize == 0
        assert params.bubble_roi_morph_close_ksize == 0
        assert params.bubble_padding_ratio == 0.95
        assert params.annotation_thickness == 2
        assert params.debug is False

    def test_custom_values(self):
        params = ImageProcessingParams(denoise_ksize=7, fill_ratio_threshold=0.5, use_bubble_classifier=True)
        assert params.denoise_ksize == 7
        assert params.fill_ratio_threshold == 0.5
        assert params.use_bubble_classifier is True

    def test_model_validate(self):
        params = ImageProcessingParams.model_validate({"denoise_ksize": 9, "adaptive_c": 10, "use_template_baseline_fill_delta": True})
        assert params.denoise_ksize == 9
        assert params.adaptive_c == 10
        assert params.use_template_baseline_fill_delta is True
        # Defaults preserved
        assert params.fill_ratio_threshold == 0.4
        assert params.delta_fill_ratio_threshold == 0.18

    def test_model_validate_empty(self):
        params = ImageProcessingParams.model_validate({})
        assert params.denoise_ksize == 5

    def test_model_dump(self):
        params = ImageProcessingParams()
        d = params.model_dump()
        assert "recognition_max_width" in d
        assert "denoise_ksize" in d
        assert "fill_ratio_threshold" in d
        assert "use_template_baseline_fill_delta" in d
        assert "delta_fill_ratio_threshold" in d
        assert d["denoise_ksize"] == 5

    def test_rejects_bool_for_new_numeric_experiment_params(self):
        with pytest.raises(ValidationError):
            ImageProcessingParams(baseline_fill_ratio_offset=True)
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_roi_morph_open_ksize=True)
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_roi_morph_close_ksize=False)
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_classifier_threshold=True)
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_classifier_delta_margin=False)

    def test_rejects_string_for_new_numeric_experiment_params(self):
        with pytest.raises(ValidationError):
            ImageProcessingParams(baseline_fill_ratio_offset="0.1")
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_roi_morph_open_ksize="3")
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_roi_morph_close_ksize="5")
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_classifier_threshold="0.5")
        with pytest.raises(ValidationError):
            ImageProcessingParams(bubble_classifier_delta_margin="0.05")
