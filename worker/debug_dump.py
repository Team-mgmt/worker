"""Debug dump primitives and the DebugObserver that drives them.

``DebugDumper`` is the low-level "write image / write JSON into the
per-job debug dir" primitive. ``DebugObserver`` subclasses
``ProcessorObserver`` and translates pipeline events into dumper calls,
so production code stays free of debug-specific branches.

Activated by ``ImageProcessingParams.debug``: when false, the processor
binds a plain no-op ``ProcessorObserver``; when true, a ``DebugObserver``
that also opens a ``Cv2Tracer`` for the duration of ``process()``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

import cv2
import numpy as np

from .cv2_trace import Cv2Tracer
from .paths import get_debug_dir
from .processor_observer import ProcessorObserver
from .types import Annotations, AreaMetrics, ImageProcessingParams

if TYPE_CHECKING:
    from zxingcpp import Barcode

    from .generated.models import ExamPaperArea

# Env flags — settable from SSM. Read at every build_observer() call so an
# operator can flip ALLOW_DEBUG=false to kill all debug instrumentation in
# the running fleet without redeploying or restarting workers.
ALLOW_DEBUG_ENV = "ALLOW_DEBUG"
ENABLE_DEBUG_ENV = "ENABLE_DEBUG"


class DebugDumper:
    """Persists images and JSON values into a per-job debug directory.

    Construct with ``enabled=False`` to short-circuit every call into a
    no-op — the directory is not even created.
    """

    def __init__(self, request_id: UUID, job_id: UUID, enabled: bool) -> None:
        self.enabled = enabled
        self._dir = get_debug_dir(request_id, job_id) if enabled else ""
        if self.enabled:
            os.makedirs(self._dir, exist_ok=True)
        # Captured here, before the surrounding ``DebugObserver`` enters
        # its ``Cv2Tracer`` and monkey-patches the cv2 module. Pipeline-
        # stage image saves below route through these unpatched refs so
        # they don't double-emit under ``cv2_calls/`` (which was both a
        # large fraction of the trace IO and a confusing duplicate in
        # the dumps).
        self._imwrite = cv2.imwrite
        self._cvtColor = cv2.cvtColor

    @classmethod
    def from_params(cls, request_id: UUID, job_id: UUID, params: ImageProcessingParams) -> "DebugDumper":
        return cls(request_id, job_id, enabled=bool(params.debug))

    @property
    def dir(self) -> str:
        return self._dir

    def _path(self, name: str) -> str:
        full = os.path.normpath(os.path.join(self._dir, name))
        if not full.startswith(os.path.normpath(self._dir) + os.sep) and full != os.path.normpath(self._dir):
            raise ValueError(f"debug dump name escapes debug dir: {name!r}")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    def save_image(self, name: str, image: np.ndarray, *, is_rgb: bool = True) -> None:
        if not self.enabled:
            return
        if not name.lower().endswith(".png"):
            name = f"{name}.png"
        path = self._path(name)
        if image.ndim == 2:
            self._imwrite(path, image)
        elif is_rgb:
            self._imwrite(path, self._cvtColor(image, cv2.COLOR_RGB2BGR))
        else:
            self._imwrite(path, image)

    def save_json(self, name: str, payload: Any) -> None:
        if not self.enabled:
            return
        if not name.lower().endswith(".json"):
            name = f"{name}.json"
        path = self._path(name)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


class DebugObserver(ProcessorObserver):
    """ProcessorObserver implementation backed by a ``DebugDumper``.

    Each ``on_*`` hook persists the relevant image or JSON snapshot.
    Per-bubble decisions are batched in memory and flushed in one JSON
    file per area kind on ``flush()``.
    """

    def __init__(self, request_id: UUID, job_id: UUID) -> None:
        self._dumper = DebugDumper(request_id, job_id, enabled=True)
        # Decisions are grouped by base_type so a single JSON file per
        # area kind is the easiest navigation surface for inspection.
        self._bubble_decisions: dict[str, list[dict]] = {}
        # Process-wide cv2 monkey-patch lives across the whole process()
        # call. on_pipeline_start enters; flush() exits. The with-block
        # alternative would have required reindenting the whole pipeline.
        self._cv2_tracer: Cv2Tracer | None = None

    # ----- pipeline lifecycle -----

    def on_pipeline_start(self, raw_processing_params: dict, parsed_params: ImageProcessingParams) -> None:
        self._dumper.save_json(
            "params.json",
            {
                "raw_metadata_processing_params": raw_processing_params,
                "parsed_params": parsed_params.model_dump(),
            },
        )
        self._cv2_tracer = Cv2Tracer(self._dumper.dir, save_images=True)
        self._cv2_tracer.__enter__()

    # ----- image stages -----

    def on_input_scan(self, image: np.ndarray) -> None:
        self._dumper.save_image("00_input_scan.png", image)

    def on_template_loaded(self, image: np.ndarray) -> None:
        self._dumper.save_image("01_template_raw.png", image)

    def on_resized(
        self,
        template: np.ndarray,
        scan: np.ndarray,
        *,
        template_source_scale: float,
        raster_to_recognition: float,
        scan_raster_to_recognition: float,
        recognition_scale: float,
        runtime_params: ImageProcessingParams,
    ) -> None:
        self._dumper.save_image("02_template_resized.png", template)
        self._dumper.save_image("03_scan_resized.png", scan)
        self._dumper.save_json(
            "recognition.json",
            {
                "template_source_scale": template_source_scale,
                "raster_to_recognition": raster_to_recognition,
                "scan_raster_to_recognition": scan_raster_to_recognition,
                "recognition_scale": recognition_scale,
                "template_width": int(template.shape[1]),
                "scan_width": int(scan.shape[1]),
            },
        )
        self._dumper.save_json("runtime_params.json", runtime_params.model_dump())

    def on_template_text_rendered(self, image: np.ndarray, rendered_count: int) -> None:
        self._dumper.save_image("03b_template_text_rendered.png", image)
        self._dumper.save_json("text_render.json", {"rendered_count": int(rendered_count)})

    def on_template_qr_rendered(self, image: np.ndarray) -> None:
        self._dumper.save_image("04_template_qr_rendered.png", image)

    def on_aligned(self, warped: np.ndarray, method: str, confidence: float) -> None:
        self._dumper.save_image("05_warped.png", warped)
        self._dumper.save_json(
            "alignment.json",
            {"method": method, "confidence": confidence},
        )

    def on_binarized(self, warped_thresh: np.ndarray, template_thresh: np.ndarray) -> None:
        self._dumper.save_image("06_warped_thresh.png", warped_thresh)
        self._dumper.save_image("07_template_thresh.png", template_thresh)

    def on_warped_annotated(self, image: np.ndarray) -> None:
        self._dumper.save_image("08_warped_annotated.png", image)

    # ----- value stages -----

    def on_qr_detected(
        self,
        exam_round_id: UUID,
        area_id: UUID,
        qrcode_map: "dict[UUID, Barcode]",
        annotations: list[Annotations],
    ) -> None:
        self._dumper.save_json(
            "qr_codes.json",
            {
                "primary": {"exam_round_id": str(exam_round_id), "area_id": str(area_id)},
                "detected_areas": sorted(str(k) for k in qrcode_map.keys()),
                "annotations": [
                    {"type": a["type"], "value": a["value"], "data": a["data"].tolist()}
                    for a in annotations
                ],
            },
        )

    def on_baseline_fill_map(self, fill_map: dict[str, float]) -> None:
        self._dumper.save_json("baseline_fill_map.json", fill_map)

    def on_bubble(
        self,
        *,
        area: "ExamPaperArea",
        local_id: str,
        crop_bbox: tuple[int, int, int, int],
        scan_region: np.ndarray,
        template_region: np.ndarray,
        baseline_fill_ratio_input: float | None,
        metrics: AreaMetrics,
        params: ImageProcessingParams,
    ) -> None:
        kind = area.area_type.base_type.value.lower() if area.area_type else "unknown"
        area_key = f"{area.id}_{local_id}"
        self._dumper.save_image(f"bubbles/{kind}/{area_key}__scan.png", scan_region)
        self._dumper.save_image(f"bubbles/{kind}/{area_key}__template.png", template_region)
        x0, y0, x1, y1 = crop_bbox
        self._bubble_decisions.setdefault(kind, []).append({
            "area_id": str(area.id),
            "area_index": area.index,
            "local_id": local_id,
            "crop": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            "metrics": dict(metrics),
            "baseline_fill_ratio_input": baseline_fill_ratio_input,
            "thresholds": {
                "fill_ratio_threshold": params.fill_ratio_threshold,
                "delta_fill_ratio_threshold": params.delta_fill_ratio_threshold,
                "absolute_fill_ratio_threshold": params.absolute_fill_ratio_threshold,
                "use_template_baseline_fill_delta": params.use_template_baseline_fill_delta,
                "use_bubble_classifier": params.use_bubble_classifier,
                "bubble_classifier_model_uri": params.bubble_classifier_model_uri,
                "bubble_classifier_threshold": float(params.bubble_classifier_threshold),
                "bubble_classifier_delta_margin": float(params.bubble_classifier_delta_margin),
            },
        })

    def on_results(
        self,
        area_metrics: dict[str, AreaMetrics],
        student_info_results: dict[int, list[str]],
        problem_results: dict[int, list[str]],
        option_results: dict[int, list[str]],
        metadata_results: dict[UUID, list[str]],
    ) -> None:
        self._dumper.save_json(
            "area_metrics.json",
            {key: dict(metrics) for key, metrics in area_metrics.items()},
        )
        self._dumper.save_json(
            "detected_results.json",
            {
                "student_info_results": {str(k): v for k, v in student_info_results.items()},
                "problem_results": {str(k): v for k, v in problem_results.items()},
                "option_results": {str(k): v for k, v in option_results.items()},
                "metadata_results": {str(k): v for k, v in metadata_results.items()},
            },
        )

    def flush(self) -> None:
        # The cv2 monkey-patch is process-global, so leaving it installed
        # after a failed flush poisons subsequent jobs (unintended tracing
        # plus unbounded ``records`` growth in a tracer no one will ever
        # call ``__exit__`` on). Run tracer teardown in a finally so disk
        # errors during ``save_json`` (OSError on full disks, permission
        # issues, etc.) cannot skip it. The inner finally guarantees the
        # reference is cleared even if ``__exit__`` itself raises, so a
        # retry-flush path can never double-restore.
        try:
            for kind, decisions in self._bubble_decisions.items():
                self._dumper.save_json(f"bubble_decisions/{kind}.json", decisions)
        finally:
            self._bubble_decisions.clear()
            if self._cv2_tracer is not None:
                try:
                    self._cv2_tracer.__exit__(None, None, None)
                finally:
                    self._cv2_tracer = None


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_debug_active(params: ImageProcessingParams) -> bool:
    """Resolve the effective debug state for this job.

    Precedence (highest first):
      1. ``ALLOW_DEBUG=false`` — hard kill switch. Ignores everything below.
      2. ``ENABLE_DEBUG=true`` — fleet-wide force-on, ignoring per-request opt-in.
      3. ``params.debug`` — per-request opt-in via metadata.processing_params.

    Defaults: ALLOW_DEBUG=true, ENABLE_DEBUG=false. So with no env set, behavior
    matches the original "debug only when the request asks for it" semantics.
    """
    if not _env_bool(ALLOW_DEBUG_ENV, default=True):
        return False
    if _env_bool(ENABLE_DEBUG_ENV, default=False):
        return True
    return bool(params.debug)


def build_observer(request_id: UUID, job_id: UUID, params: ImageProcessingParams) -> ProcessorObserver:
    """Factory used by processors: returns a no-op observer unless debug is on."""
    if is_debug_active(params):
        return DebugObserver(request_id, job_id)
    return ProcessorObserver()
