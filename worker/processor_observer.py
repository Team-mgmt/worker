"""Observer interface for the scan-processing pipeline.

The processor emits one observer call per pipeline event so the main
flow reads as a clean sequence of operations. The default
``ProcessorObserver`` is a no-op; ``DebugObserver`` (in
``worker/debug_dump.py``) overrides each hook to persist images,
JSON values, and a per-call cv2 trace into the per-job debug dir.

Hook calls are positional/keyword-clean and use no truthiness checks,
so production code paths stay free of ``if debug:`` branching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    import numpy as np
    from zxingcpp import Barcode

    from .generated.models import ExamPaperArea
    from .types import Annotations, AreaMetrics, ImageProcessingParams


class ProcessorObserver:
    """No-op observer. Subclass and override hooks to react to events."""

    # ----- pipeline lifecycle -----

    def on_pipeline_start(
        self,
        raw_processing_params: dict,
        parsed_params: "ImageProcessingParams",
    ) -> None:
        return None

    # ----- image stages -----

    def on_input_scan(self, image: "np.ndarray") -> None:
        return None

    def on_template_loaded(self, image: "np.ndarray") -> None:
        return None

    def on_resized(
        self,
        template: "np.ndarray",
        scan: "np.ndarray",
        *,
        template_source_scale: float,
        raster_to_recognition: float,
        scan_raster_to_recognition: float,
        recognition_scale: float,
        runtime_params: "ImageProcessingParams",
    ) -> None:
        return None

    def on_template_text_rendered(self, image: "np.ndarray", rendered_count: int) -> None:
        return None

    def on_template_qr_rendered(self, image: "np.ndarray") -> None:
        return None

    def on_aligned(self, warped: "np.ndarray", method: str, confidence: float) -> None:
        return None

    def on_binarized(self, warped_thresh: "np.ndarray", template_thresh: "np.ndarray") -> None:
        return None

    def on_warped_annotated(self, image: "np.ndarray") -> None:
        return None

    # ----- value stages -----

    def on_qr_detected(
        self,
        exam_round_id: "UUID",
        area_id: "UUID",
        qrcode_map: "dict[UUID, Barcode]",
        annotations: "list[Annotations]",
    ) -> None:
        return None

    def on_baseline_fill_map(self, fill_map: dict[str, float]) -> None:
        return None

    def on_bubble(
        self,
        *,
        area: "ExamPaperArea",
        local_id: str,
        crop_bbox: tuple[int, int, int, int],
        scan_region: "np.ndarray",
        template_region: "np.ndarray",
        baseline_fill_ratio_input: float | None,
        metrics: "AreaMetrics",
        params: "ImageProcessingParams",
    ) -> None:
        return None

    def on_results(
        self,
        area_metrics: "dict[str, AreaMetrics]",
        student_info_results: dict[int, list[str]],
        problem_results: dict[int, list[str]],
        option_results: dict[int, list[str]],
        metadata_results: "dict[UUID, list[str]]",
    ) -> None:
        return None

    def flush(self) -> None:
        """Persist any batched state. Called once at end of process()."""
        return None
