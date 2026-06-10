from typing import Literal, NotRequired, TypedDict
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, field_validator

PositionLiteral = Literal["LT", "RT", "RB", "LB"]


class ProcessError(Exception):
    """Error during scan processing with backend-friendly error code and params.

    Args:
        message: Human-readable error message
        code: Backend-friendly error code (e.g., "OPTION_NOT_DETECTED", "QR_NOT_FOUND")
        params: Additional parameters for the error (e.g., {"missing_areas": ["홀수형/짝수형"]})
    """

    def __init__(self, message: str, *, code: str | None = None, params: dict | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.message = message
        self.code = code
        self.params = params


class Annotations(TypedDict):
    data: np.ndarray
    type: str
    value: str


BubbleShape = Literal["ellipse", "rect"]


class ProcessingMeta(TypedDict):
    """Stable, explicit signals about how a scan was measured.

    Downstream systems depend on these to interpret `area_metrics`.
    Keep keys backwards-compatible; add new keys rather than repurposing.
    """

    bubble_shape: BubbleShape  # geometric shape used to mask the bubble area


class AreaMetrics(TypedDict):
    """Metrics calculated during filled area detection."""

    version: int  # processor version (1 or 2)
    is_filled: bool
    # v1 metrics
    fill_ratio: NotRequired[float]  # black pixel ratio inside the measured bubble ROI
    baseline_fill_ratio: NotRequired[float]  # raw template baseline ratio inside the same ROI
    adjusted_baseline_fill_ratio: NotRequired[float]  # decision-time baseline after configured offset
    delta_fill_ratio: NotRequired[float]  # scanned fill ratio minus decision-time template baseline
    rule_is_filled: NotRequired[bool]  # original rule-based verdict before any classifier assist
    classifier_ambiguous: NotRequired[bool]  # whether the bubble fell inside the assist margin
    classifier_invoked: NotRequired[bool]  # whether the classifier produced a prediction
    classifier_probability: NotRequired[float]  # p(filled) from the classifier
    classifier_predicted_filled: NotRequired[bool]  # classifier verdict before fallback handling
    classifier_fallback_used: NotRequired[bool]  # whether processing fell back to the rule-based verdict
    classifier_error: NotRequired[str]  # model load / inference failure details for debug
    classifier_model_uri: NotRequired[str]  # model artifact used when assist mode is enabled


class ChildPosition(TypedDict):
    """Position of a child area within a parent area (in mm, relative to parent)."""

    x: float
    y: float
    width: float
    height: float


class ProcessResult(TypedDict):
    organization_id: UUID
    exam_id: UUID
    exam_round_id: UUID
    annotations: list[Annotations]
    annotations_cropped: list[Annotations]
    image_annotated_cropped_path: str
    image_flattened_path: str
    image_threshold_path: str
    area_image_paths: dict[str, str]
    area_metrics: dict[str, AreaMetrics]
    student_info_results: dict[int, list[str]]  # area.index -> detected localIds
    problem_results: dict[int, list[str]]  # area.index -> detected localIds
    option_results: dict[int, list[str]]  # area.index -> detected localIds
    # area.id -> detected localIds. Keyed by ExamPaperArea.id (not area.index)
    # because METADATA areas have no associated ExamProblem to remap through.
    metadata_results: NotRequired[dict[UUID, list[str]]]
    processing_params: "ImageProcessingParams"
    processing_meta: ProcessingMeta


class ImageProcessingParams(BaseModel):
    """Parameters for cv2 image processing, with sensible defaults."""

    # Recognition resolution
    recognition_scale: float = 1.0  # effective scale used for ROI reading; can be overridden for experiments
    recognition_max_width: int = 4000  # 0 to disable downscaling
    reference_template_width: int = 2480  # width on which morphology kernels were tuned

    # Minimum raster width for SVG templates. SVGs whose intrinsic width is
    # below this are upscaled (preserving aspect ratio) so OMR detection
    # bubbles get enough pixels to be noise-robust; the user-unit→raster-pixel
    # factor is propagated into ``recognition_scale`` so area coordinates
    # still translate correctly through the recognition resize. The cap on
    # rendered pixels (see ``util.SVG_MAX_INTRINSIC_PIXELS``) clamps the
    # upscale factor for unusually tall/narrow SVGs. Set to 1 to effectively
    # disable upscaling.
    svg_min_render_width: int = Field(default=4800, gt=0)
    adaptive_kernel_scaling: bool = True
    morph_close_first: bool = True
    min_morph_kernel_size: int = 1

    # Binarization (binarize_document)
    denoise_ksize: int = 5  # MedianBlur kernel size for denoising (must be odd)
    adaptive_block_ratio: float = 0.02  # Adaptive threshold block size as ratio of min(h,w)
    adaptive_block_min: int = 31  # Minimum adaptive threshold block size
    adaptive_c: int = 7  # Adaptive threshold C constant, tune 3~15
    post_thresh_ksize: int = 3  # MedianBlur kernel size after thresholding for salt/pepper noise (0 to disable)
    morph_open_ksize: int = 0  # Morphology open kernel size (0 to disable)
    morph_close_ksize: int = 0  # Morphology close kernel size (0 to disable)

    # Fill ratio threshold for detecting filled areas (v1)
    fill_ratio_threshold: float = 0.4
    use_template_baseline_fill_delta: bool = True
    delta_fill_ratio_threshold: float = 0.18
    absolute_fill_ratio_threshold: float | None = None
    baseline_fill_ratio_offset: StrictFloat | StrictInt = Field(default=0, ge=0.0, allow_inf_nan=False)
    use_bubble_classifier: StrictBool = False
    bubble_classifier_model_uri: str | None = None
    bubble_classifier_threshold: StrictFloat | StrictInt = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)
    bubble_classifier_delta_margin: StrictFloat | StrictInt = Field(default=0.05, ge=0.0, allow_inf_nan=False)

    # Bubble measurement geometry / ROI processing.
    bubble_measurement_shape: BubbleShape = "rect"
    bubble_roi_use_morphology: bool = False
    bubble_roi_morph_close_first: bool = True
    bubble_roi_morph_open_ksize: StrictInt = 0
    bubble_roi_morph_close_ksize: StrictInt = 0

    # Multiplier applied to the bubble bbox width and height to derive the
    # measurement crop; the bubble center is preserved.
    # 1.0 = crop matches the original bbox (no padding);
    # 0.9 = 10% inward shrink; 1.1 = 10% outward expansion.
    bubble_padding_ratio: float = Field(default=0.95, gt=0.0, allow_inf_nan=False)

    # Annotation line thickness
    annotation_thickness: int = 2

    # When true, ProcessorV1 dumps every mutated image (resized scan/template,
    # QR-rendered template, warped image, threshold maps, per-bubble crops,
    # annotated output) and every considered value (per-bubble fill metrics
    # with the decision threshold, alignment confidence, recognition scale,
    # runtime params) into ``STORAGE_DIR/debug/<request_id>/<job_id>/``. Off
    # by default; the dump path lives outside the per-job results dir so the
    # post-job cleanup leaves it intact for inspection.
    debug: bool = False

    @field_validator(
        "baseline_fill_ratio_offset",
        "bubble_roi_morph_open_ksize",
        "bubble_roi_morph_close_ksize",
        "bubble_classifier_threshold",
        "bubble_classifier_delta_margin",
        mode="before",
    )
    @classmethod
    def _reject_bool_for_numeric_experiments(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("numeric experiment params must be numbers, not bool")
        return value
