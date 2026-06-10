"""Version 1.0 processor for QMR paper processing.

This processor uses:
- QR code detection only (no DataMatrix)
- RoMaV2 deep learning model for scan-to-template alignment
- Simplified binarization and area detection
"""

import asyncio
import os

import cv2
import numpy as np

from .. import cache, telemetry
from ..bubble_classifier import ResNet18BubbleClassifier, get_or_load_resnet18_bubble_classifier
from ..cv2_span_trace import trace_cv2_spans
from ..debug_dump import build_observer
from ..generated.models import Exam, ExamPaper, ExamPaperArea, ExamRound
from ..matcher import DocumentMatcher
from ..paths import get_result_path, get_results_dir
from ..text_render import render_text_areas_on_template
from ..types import UUID, Annotations, AreaMetrics, ChildPosition, ImageProcessingParams, ProcessError, ProcessingMeta, ProcessResult
from ..util import prepare_image, render_qrcode_on_template
from .base import BaseProcessor

ROMAV2_MIN_CONFIDENCE = 0.3


class ProcessorV1(BaseProcessor):
    """Version 1.0 processor for QMR paper processing.

    Uses RoMaV2 for robust scan-to-template alignment.

    Features:
    - QR code detection only (no DataMatrix required)
    - Uses RoMaV2 dense matching for alignment
    - Simpler, more robust alignment pipeline
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._matcher = DocumentMatcher.get_instance()

    def _resize_for_recognition(self, image: np.ndarray, max_width: int, explicit_scale: float = 1.0) -> tuple[np.ndarray, float]:
        """Resize image for recognition and return the applied scale."""
        height, width = image.shape[:2]
        if 0 < explicit_scale < 1.0:
            resized = cv2.resize(
                image,
                (max(1, int(round(width * explicit_scale))), max(1, int(round(height * explicit_scale)))),
                interpolation=cv2.INTER_AREA,
            )
            return resized, explicit_scale
        if max_width <= 0 or width <= max_width:
            return image, 1.0

        scale = max_width / float(width)
        resized = cv2.resize(
            image,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, scale

    def _scale_position(self, value: float | int, scale: float) -> int:
        return int(round(float(value) * scale))

    def _scale_length(self, value: float | int, scale: float) -> int:
        return max(1, int(round(float(value) * scale)))

    def _scaled_kernel_size(self, kernel_size: int, working_width: int, params: ImageProcessingParams) -> int:
        """Scale morphology kernels to the current recognition width."""
        if kernel_size <= 0:
            return 0

        scaled = kernel_size
        if params.adaptive_kernel_scaling and params.reference_template_width > 0:
            scaled = int(round(kernel_size * working_width / float(params.reference_template_width)))
        scaled = max(params.min_morph_kernel_size, scaled)
        return self._odd_at_least(scaled, at_least=params.min_morph_kernel_size)

    def _process_child_areas(
        self,
        warped_thresh: cv2.typing.MatLike,
        template_thresh: cv2.typing.MatLike,
        areas: list[ExamPaperArea],
        request_id: UUID,
        job_id: UUID,
        params: ImageProcessingParams,
        baseline_fill_map: dict[str, float] | None = None,
        bubble_classifier: ResNet18BubbleClassifier | None = None,
        bubble_classifier_load_error: str | None = None,
    ) -> tuple[list[Annotations], dict[int, list[str]], dict[str, str], dict[str, AreaMetrics]]:
        """Process child areas and return detected localIds.

        Selects ALL choices above the fill threshold for each area.
        Works the same for both IDENTIFIER and PROBLEM areas - the detection
        logic is identical. IDENTIFIER stringification happens via backend API.

        Args:
            warped_thresh: Binarized warped image
            areas: List of ExamPaperArea to process (coordinates in template pixels)
            request_id: Request UUID for file paths
            job_id: Job UUID for file paths
            params: Image processing parameters

        Returns:
            Tuple of (annotations, detected_data, area_image_paths, area_metrics)
            - detected_data: dict[area.index, list[detected_localIds]]
        """
        annotations: list[Annotations] = []
        area_image_paths: dict[str, str] = {}
        area_metrics: dict[str, AreaMetrics] = {}
        detected_data: dict[int, list[str]] = {}

        img_h, img_w = warped_thresh.shape[:2]

        for area in areas:
            children: dict[str, ChildPosition] = area.data.get("children", {})
            detected_local_ids: list[str] = []

            for local_id, child_pos in children.items():
                pos_x_px, pos_y_px, width_px, height_px = self._bubble_crop_bounds(
                    area.pos_x, area.pos_y, child_pos, params.bubble_padding_ratio, params.recognition_scale
                )

                # Clip the desired crop to image bounds. With ratio > 1, the
                # bubble can extend past the page edge; numpy negative slicing
                # would silently wrap, so clamp explicitly.
                x0 = max(0, pos_x_px)
                y0 = max(0, pos_y_px)
                x1 = min(img_w, pos_x_px + width_px)
                y1 = min(img_h, pos_y_px + height_px)
                if x1 <= x0 or y1 <= y0:
                    continue

                child_region = warped_thresh[y0:y1, x0:x1]
                template_region = template_thresh[y0:y1, x0:x1]

                area_key = f"{area.id}_{local_id}"
                area_path = self._save_area_image(request_id, job_id, child_region, area_key)
                area_image_paths[area_key] = area_path
                baseline_fill_ratio: float | None = None
                if params.use_template_baseline_fill_delta:
                    baseline_key = self._baseline_fill_map_key(area.id, local_id)
                    baseline_fill_ratio = baseline_fill_map.get(baseline_key, 0.0) if baseline_fill_map is not None else 0.0

                metrics = self._check_filled_area(child_region, template_region, params, baseline_fill_ratio)
                metrics = self._apply_bubble_classifier_assist(
                    area_key=area_key,
                    image=child_region,
                    metrics=metrics,
                    params=params,
                    bubble_classifier=bubble_classifier,
                    bubble_classifier_load_error=bubble_classifier_load_error,
                )
                area_metrics[area_key] = metrics

                if metrics["is_filled"]:
                    detected_local_ids.append(local_id)

                self._observer.on_bubble(
                    area=area,
                    local_id=local_id,
                    crop_bbox=(x0, y0, x1, y1),
                    scan_region=child_region,
                    template_region=template_region,
                    baseline_fill_ratio_input=baseline_fill_ratio,
                    metrics=metrics,
                    params=params,
                )

                corners = [
                    (x0, y0),
                    (x1, y0),
                    (x1, y1),
                    (x0, y1),
                ]
                annotations.append(
                    Annotations(
                        data=np.array(corners, dtype=np.int32),
                        type="area_inferred_child",
                        value=f"{area.area_type.base_type.value}_{area.id}_{local_id}",
                    )
                )

            detected_data[area.index] = detected_local_ids

        return annotations, detected_data, area_image_paths, area_metrics

    def _schedule_warn(self, message: str) -> None:
        try:
            asyncio.get_running_loop().create_task(self._logger.warn(message))
        except RuntimeError:
            pass

    def _should_use_bubble_classifier_assist(self, metrics: AreaMetrics, params: ImageProcessingParams) -> bool:
        if not params.use_bubble_classifier or not params.bubble_classifier_model_uri:
            return False
        if not params.use_template_baseline_fill_delta:
            return False
        delta_fill_ratio = metrics.get("delta_fill_ratio")
        if delta_fill_ratio is None:
            return False
        return abs(delta_fill_ratio - params.delta_fill_ratio_threshold) <= float(params.bubble_classifier_delta_margin)

    def _apply_bubble_classifier_assist(
        self,
        *,
        area_key: str,
        image: np.ndarray,
        metrics: AreaMetrics,
        params: ImageProcessingParams,
        bubble_classifier: ResNet18BubbleClassifier | None,
        bubble_classifier_load_error: str | None,
    ) -> AreaMetrics:
        if not params.use_bubble_classifier:
            return metrics

        metrics["rule_is_filled"] = metrics["is_filled"]
        metrics["classifier_model_uri"] = params.bubble_classifier_model_uri or ""
        metrics["classifier_ambiguous"] = False
        metrics["classifier_invoked"] = False
        metrics["classifier_fallback_used"] = False

        if not self._should_use_bubble_classifier_assist(metrics, params):
            return metrics

        metrics["classifier_ambiguous"] = True

        if bubble_classifier is None:
            metrics["classifier_fallback_used"] = True
            if bubble_classifier_load_error:
                metrics["classifier_error"] = bubble_classifier_load_error
            return metrics

        try:
            probability = bubble_classifier.predict_filled_probability(image)
        except Exception as exc:
            message = f"[ProcessorV1] Bubble classifier inference failed for {area_key}: {exc!r}. Falling back to rule-based verdict."
            metrics["classifier_fallback_used"] = True
            metrics["classifier_error"] = message
            self._schedule_warn(message)
            return metrics

        predicted_filled = probability >= float(params.bubble_classifier_threshold)
        metrics["classifier_invoked"] = True
        metrics["classifier_probability"] = probability
        metrics["classifier_predicted_filled"] = predicted_filled
        metrics["is_filled"] = predicted_filled
        return metrics

    def _bubble_ellipse_mask(self, height: int, width: int) -> np.ndarray:
        """Build a uint8 mask (255 inside the inscribed ellipse, 0 outside).

        A pixel is included only if its full extent lies strictly inside the
        inscribed ellipse ??i.e., the pixel's farthest corner from the bbox
        center is strictly inside (`(dx/rx)^2 + (dy/ry)^2 < 1`). Pixels
        crossed by the ellipse boundary are excluded.
        """
        if height <= 0 or width <= 0:
            return np.zeros((max(0, height), max(0, width)), dtype=np.uint8)

        cx = width / 2.0
        cy = height / 2.0
        rx = width / 2.0
        ry = height / 2.0
        if rx <= 0 or ry <= 0:
            return np.zeros((height, width), dtype=np.uint8)

        ys = np.arange(height)
        xs = np.arange(width)
        xx, yy = np.meshgrid(xs, ys)
        # Each pixel covers the unit square centered at (x+0.5, y+0.5); the
        # corner farthest from the ellipse center sits at +/-0.5 along both
        # axes from the pixel center, away from the ellipse center.
        far_dx = np.abs(xx + 0.5 - cx) + 0.5
        far_dy = np.abs(yy + 0.5 - cy) + 0.5
        inside = (far_dx / rx) ** 2 + (far_dy / ry) ** 2 < 1.0
        return (inside.astype(np.uint8) * 255)

    def _bubble_crop_bounds(
        self,
        area_pos_x: float,
        area_pos_y: float,
        child_pos: ChildPosition,
        padding_ratio: float,
        scale: float,
    ) -> tuple[int, int, int, int]:
        """Compute the bubble crop region in recognition-pixel coords.

        The bubble center (bbox center) is preserved; width and height are
        scaled by `padding_ratio` and the top-left is recomputed so the
        ellipse stays centered on the original bubble center.
        Returns `(pos_x_px, pos_y_px, width_px, height_px)`.
        """
        orig_x = area_pos_x + child_pos["x"]
        orig_y = area_pos_y + child_pos["y"]
        orig_w = float(child_pos["width"])
        orig_h = float(child_pos["height"])

        cx = orig_x + orig_w / 2.0
        cy = orig_y + orig_h / 2.0
        eff_w = orig_w * padding_ratio
        eff_h = orig_h * padding_ratio
        eff_x = cx - eff_w / 2.0
        eff_y = cy - eff_h / 2.0

        return (
            self._scale_position(eff_x, scale),
            self._scale_position(eff_y, scale),
            self._scale_length(eff_w, scale),
            self._scale_length(eff_h, scale),
        )

    def _baseline_fill_map_key(self, area_id: UUID, local_id: str) -> str:
        return f"{area_id}:{local_id}"

    def _apply_rect_roi_morphology(
        self,
        image: cv2.typing.MatLike,
        params: ImageProcessingParams,
    ) -> cv2.typing.MatLike:
        """Optionally apply morphology to a binary ROI before rect measurement.

        Bubble ROIs are binary document crops with black ink as 0 and white
        background as 255. Morphology in OpenCV treats non-zero pixels as the
        foreground, so invert first, morph the ink mask, then invert back.
        """
        if image.shape[0] == 0 or image.shape[1] == 0:
            return image
        if not params.bubble_roi_use_morphology:
            return image

        working = cv2.bitwise_not(image)
        open_ksize = self._odd_at_least(params.bubble_roi_morph_open_ksize, at_least=1) if params.bubble_roi_morph_open_ksize > 0 else 0
        close_ksize = self._odd_at_least(params.bubble_roi_morph_close_ksize, at_least=1) if params.bubble_roi_morph_close_ksize > 0 else 0

        if params.bubble_roi_morph_close_first:
            morph_ops = (
                (cv2.MORPH_CLOSE, close_ksize),
                (cv2.MORPH_OPEN, open_ksize),
            )
        else:
            morph_ops = (
                (cv2.MORPH_OPEN, open_ksize),
                (cv2.MORPH_CLOSE, close_ksize),
            )

        for op, ksize in morph_ops:
            if ksize <= 0:
                continue
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, ksize))
            working = cv2.morphologyEx(working, op, kernel)

        return cv2.bitwise_not(working)

    def _measure_scanned_fill_ratio(
        self,
        image: cv2.typing.MatLike,
        template: cv2.typing.MatLike,
    ) -> float:
        """Measure user-added darkness over the template-clear portion of the bubble."""
        if image.shape[0] == 0 or image.shape[1] == 0:
            return 0.0

        mask = self._bubble_ellipse_mask(image.shape[0], image.shape[1])
        if cv2.countNonZero(mask) == 0:
            return 0.0

        inverted = cv2.bitwise_not(image)
        template_inverted = cv2.bitwise_not(template)
        template_clear = cv2.bitwise_not(template_inverted)
        user_area = cv2.bitwise_and(mask, template_clear)
        user_area_count = float(cv2.countNonZero(user_area))
        if user_area_count == 0:
            return 0.0

        user_marks = cv2.bitwise_and(inverted, user_area)
        user_mark_count = float(cv2.countNonZero(user_marks))
        return user_mark_count / user_area_count

    def _measure_scanned_rect_fill_ratio(
        self,
        image: cv2.typing.MatLike,
        template: cv2.typing.MatLike,
        params: ImageProcessingParams,
    ) -> float:
        """Measure user-added darkness over the template-clear portion of the ROI rectangle."""
        if image.shape[0] == 0 or image.shape[1] == 0:
            return 0.0

        measured_image = self._apply_rect_roi_morphology(image, params)
        measured_template = self._apply_rect_roi_morphology(template, params)
        user_area_count = float(cv2.countNonZero(measured_template))
        if user_area_count == 0:
            return 0.0

        inverted = cv2.bitwise_not(measured_image)
        user_marks = cv2.bitwise_and(inverted, measured_template)
        return float(cv2.countNonZero(user_marks)) / user_area_count

    def _measure_ellipse_fill_ratio(
        self,
        image: cv2.typing.MatLike,
    ) -> float:
        """Measure darkness directly inside the full inscribed ellipse."""
        if image.shape[0] == 0 or image.shape[1] == 0:
            return 0.0

        mask = self._bubble_ellipse_mask(image.shape[0], image.shape[1])
        ellipse_area = float(cv2.countNonZero(mask))
        if ellipse_area == 0:
            return 0.0

        inverted = cv2.bitwise_not(image)
        marks = cv2.bitwise_and(inverted, mask)
        return float(cv2.countNonZero(marks)) / ellipse_area

    def _measure_rect_fill_ratio(
        self,
        image: cv2.typing.MatLike,
        params: ImageProcessingParams,
    ) -> float:
        """Measure darkness directly over the full ROI rectangle."""
        if image.shape[0] == 0 or image.shape[1] == 0:
            return 0.0

        measured_image = self._apply_rect_roi_morphology(image, params)
        roi_area = float(measured_image.shape[0] * measured_image.shape[1])
        if roi_area == 0:
            return 0.0

        inverted = cv2.bitwise_not(measured_image)
        return float(cv2.countNonZero(inverted)) / roi_area

    def _measure_template_baseline_fill_ratio(
        self,
        template: cv2.typing.MatLike,
        params: ImageProcessingParams,
    ) -> float:
        """Measure template darkness directly inside the active bubble ROI."""
        if params.bubble_measurement_shape == "rect":
            return self._measure_rect_fill_ratio(template, params)
        return self._measure_ellipse_fill_ratio(template)

    def _decide_is_filled(
        self,
        fill_ratio: float,
        baseline_fill_ratio: float,
        params: ImageProcessingParams,
    ) -> tuple[bool, float]:
        delta_fill_ratio = fill_ratio - baseline_fill_ratio
        if not params.use_template_baseline_fill_delta:
            return fill_ratio > params.fill_ratio_threshold, delta_fill_ratio

        is_filled = delta_fill_ratio > params.delta_fill_ratio_threshold
        if params.absolute_fill_ratio_threshold is not None:
            is_filled = is_filled and fill_ratio > params.absolute_fill_ratio_threshold
        return is_filled, delta_fill_ratio

    def _check_filled_area(
        self,
        image: cv2.typing.MatLike,
        template: cv2.typing.MatLike,
        params: ImageProcessingParams,
        baseline_fill_ratio: float | None = None,
    ) -> AreaMetrics:
        """Check if the area is filled using the active bubble measurement ROI.

        Legacy absolute mode measures user-added darkness over the template-clear
        portion of the ROI. Template-baseline delta mode measures direct darkness
        over the ROI and subtracts the template baseline measured over that same
        ROI; the baseline can be padded by ``baseline_fill_ratio_offset`` to
        compensate for rasterization thickening in printed/photo scans.
        """
        raw_baseline_fill_ratio = baseline_fill_ratio if baseline_fill_ratio is not None else 0.0
        adjusted_baseline_fill_ratio = raw_baseline_fill_ratio
        if params.use_template_baseline_fill_delta:
            if params.bubble_measurement_shape == "rect":
                fill_ratio = self._measure_rect_fill_ratio(image, params)
                adjusted_baseline_fill_ratio = min(1.0, raw_baseline_fill_ratio + float(params.baseline_fill_ratio_offset))
            else:
                fill_ratio = self._measure_ellipse_fill_ratio(image)
        else:
            if params.bubble_measurement_shape == "rect":
                fill_ratio = self._measure_scanned_rect_fill_ratio(image, template, params)
            else:
                fill_ratio = self._measure_scanned_fill_ratio(image, template)
            raw_baseline_fill_ratio = 0.0
            adjusted_baseline_fill_ratio = 0.0

        is_filled, delta_fill_ratio = self._decide_is_filled(fill_ratio, adjusted_baseline_fill_ratio, params)
        return AreaMetrics(
            version=1,
            is_filled=is_filled,
            fill_ratio=fill_ratio,
            baseline_fill_ratio=raw_baseline_fill_ratio,
            adjusted_baseline_fill_ratio=adjusted_baseline_fill_ratio,
            delta_fill_ratio=delta_fill_ratio,
        )


    def _odd_at_least(self, n: int, at_least: int = 3) -> int:
        n = max(at_least, int(n))
        return n | 1

    def _binarize_document(self, image: np.ndarray, params: ImageProcessingParams) -> np.ndarray:
        """Binarize document image using adaptive thresholding."""
        # Convert to grayscale using L channel from LAB
        if len(image.shape) == 3:
            lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
            gray = lab[:, :, 0]
        else:
            gray = image

        gray = cv2.medianBlur(gray, params.denoise_ksize)

        h, w = gray.shape
        block = self._odd_at_least(int(min(h, w) * params.adaptive_block_ratio), at_least=params.adaptive_block_min)
        thresh = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=block,
            C=params.adaptive_c,
        )

        close_ksize = self._scaled_kernel_size(params.morph_close_ksize, w, params)
        open_ksize = self._scaled_kernel_size(params.morph_open_ksize, w, params)
        if params.morph_close_first:
            morph_ops = [
                (cv2.MORPH_CLOSE, close_ksize),
                (cv2.MORPH_OPEN, open_ksize),
            ]
        else:
            morph_ops = [
                (cv2.MORPH_OPEN, open_ksize),
                (cv2.MORPH_CLOSE, close_ksize),
            ]

        for op, ksize in morph_ops:
            if ksize <= 0:
                continue
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
            thresh = cv2.morphologyEx(thresh, op, kernel)

        if params.post_thresh_ksize > 0:
            ksize = self._odd_at_least(params.post_thresh_ksize)
            thresh = cv2.medianBlur(thresh, ksize)

        return thresh

    async def _get_or_binarize_template(
        self,
        exam_paper: ExamPaper,
        exam: Exam,
        exam_round: ExamRound,
        template_image: np.ndarray,
        params: ImageProcessingParams,
        *,
        cacheable: bool = True,
    ) -> np.ndarray:
        """Binarize template, reading through a disk cache.

        Safe to cache the pre-QR-render template because child areas (IDENTIFIER,
        PROBLEM, OPTION) never overlap QRCODE areas, so post-render QR pixels are
        not read from template_thresh. The cached binarization *does* include
        TEXT-area renderings (drawn before this point), so the cache key folds
        in ``exam_paper.updated_at``, ``exam.updated_at``, and
        ``exam_round.id``/``updated_at`` — different rounds under the same exam
        substitute different ``{EXAM_ROUND_NAME}`` text and must not share an
        entry.

        ``cacheable=False`` bypasses both cache read and write. The caller uses
        this when the template pixels are known to be incomplete (e.g. TEXT
        rendering hit a transient S3 error) so a partial binarization is not
        served back to future scans.
        """
        # Cache I/O is non-fatal: filesystem errors / permission issues /
        # cleanup races degrade to a miss on read and a no-op on write, since
        # binarization itself doesn't need cache persistence to succeed.
        if cacheable:
            try:
                cached = await asyncio.to_thread(
                    cache.get_template_thresh,
                    exam_paper.id,
                    exam_paper.updated_at,
                    exam.id,
                    exam.updated_at,
                    exam_round.id,
                    exam_round.updated_at,
                    exam_paper.background_image,
                    params,
                )
            except (OSError, cv2.error) as e:
                await self._logger.warn(f"[ProcessorV1] Template thresh cache read failed ({e}); treating as miss")
                cached = None

            if cached is not None:
                telemetry.record_cache_lookup("template_thresh", hit=True)
                await self._logger.info(f"[ProcessorV1] Template thresh cache hit for {exam_paper.id}")
                return cached
            telemetry.record_cache_lookup("template_thresh", hit=False)
            await self._logger.info(f"[ProcessorV1] Template thresh cache miss for {exam_paper.id}")
        else:
            await self._logger.info(
                f"[ProcessorV1] Template thresh cache bypassed for {exam_paper.id} (template incomplete)"
            )

        result = await asyncio.to_thread(self._binarize_document, template_image, params)

        if cacheable:
            try:
                await asyncio.to_thread(
                    cache.put_template_thresh,
                    exam_paper.id,
                    exam_paper.updated_at,
                    exam.id,
                    exam.updated_at,
                    exam_round.id,
                    exam_round.updated_at,
                    exam_paper.background_image,
                    params,
                    result,
                )
            except (OSError, cv2.error) as e:
                await self._logger.warn(f"[ProcessorV1] Template thresh cache write failed ({e}); continuing without cache")

        return result

    def _compute_template_baseline_fill_map(
        self,
        template_thresh: cv2.typing.MatLike,
        areas: list[ExamPaperArea],
        params: ImageProcessingParams,
    ) -> dict[str, float]:
        """Compute per-bubble baseline darkness from the template image itself."""
        fill_map: dict[str, float] = {}
        img_h, img_w = template_thresh.shape[:2]

        for area in areas:
            children: dict[str, ChildPosition] = area.data.get("children", {})
            for local_id, child_pos in children.items():
                pos_x_px, pos_y_px, width_px, height_px = self._bubble_crop_bounds(
                    area.pos_x, area.pos_y, child_pos, params.bubble_padding_ratio, params.recognition_scale
                )

                x0 = max(0, pos_x_px)
                y0 = max(0, pos_y_px)
                x1 = min(img_w, pos_x_px + width_px)
                y1 = min(img_h, pos_y_px + height_px)
                if x1 <= x0 or y1 <= y0:
                    continue

                template_region = template_thresh[y0:y1, x0:x1]
                fill_map[self._baseline_fill_map_key(area.id, local_id)] = self._measure_template_baseline_fill_ratio(template_region, params)

        return fill_map

    async def _get_or_compute_template_baseline_fill_map(
        self,
        exam_paper: ExamPaper,
        exam: Exam,
        exam_round: ExamRound,
        template_thresh: np.ndarray,
        areas: list[ExamPaperArea],
        params: ImageProcessingParams,
        *,
        cacheable: bool = True,
    ) -> dict[str, float]:
        """Read the template baseline map through cache, computing on miss.

        ``cacheable=False`` bypasses both cache read and write; the caller uses
        this when the underlying ``template_thresh`` was binarized from a
        template whose TEXT rendering didn't complete, so baselines measured
        against it would be partial.
        """
        if cacheable:
            # ValueError covers json.JSONDecodeError and float() failures on a
            # corrupted cache file; degrade to a miss rather than aborting the scan.
            try:
                cached = await asyncio.to_thread(
                    cache.get_template_baseline_fill_map,
                    exam_paper.id,
                    exam_paper.updated_at,
                    exam.id,
                    exam.updated_at,
                    exam_round.id,
                    exam_round.updated_at,
                    exam_paper.background_image,
                    params,
                    areas,
                )
            except (OSError, ValueError) as e:
                await self._logger.warn(f"[ProcessorV1] Template baseline cache read failed ({e}); treating as miss")
                cached = None

            if cached is not None:
                await self._logger.info(f"[ProcessorV1] Template baseline cache hit for {exam_paper.id}")
                return cached
            await self._logger.info(f"[ProcessorV1] Template baseline cache miss for {exam_paper.id}")
        else:
            await self._logger.info(
                f"[ProcessorV1] Template baseline cache bypassed for {exam_paper.id} (template incomplete)"
            )

        result = await asyncio.to_thread(self._compute_template_baseline_fill_map, template_thresh, areas, params)

        if not cacheable:
            return result

        try:
            await asyncio.to_thread(
                cache.put_template_baseline_fill_map,
                exam_paper.id,
                exam_paper.updated_at,
                exam.id,
                exam.updated_at,
                exam_round.id,
                exam_round.updated_at,
                exam_paper.background_image,
                params,
                areas,
                result,
            )
        except OSError as e:
            await self._logger.warn(f"[ProcessorV1] Template baseline cache write failed ({e}); continuing without cache")

        return result

    def _save_output_images(
        self,
        request_id: UUID,
        job_id: UUID,
        warped_thresh: cv2.typing.MatLike,
        warped_image: cv2.typing.MatLike,
    ) -> tuple[str, str]:
        """Save threshold and flattened images to disk.

        Returns:
            Tuple of (threshold_path, flattened_path)
        """
        threshold_path = get_result_path(request_id, job_id, "threshold.png")
        threshold_ok, threshold_encoded = cv2.imencode(".png", warped_thresh)
        if not threshold_ok:
            raise OSError("Failed to encode threshold image as PNG")
        threshold_encoded.tofile(threshold_path)

        flattened_path = get_result_path(request_id, job_id, "flattened.png")
        flattened_ok, flattened_encoded = cv2.imencode(".png", cv2.cvtColor(warped_image, cv2.COLOR_RGB2BGR))
        if not flattened_ok:
            raise OSError("Failed to encode flattened image as PNG")
        flattened_encoded.tofile(flattened_path)

        return threshold_path, flattened_path

    async def process(self, image: cv2.typing.MatLike, job_id: UUID, request_id: UUID, metadata: dict) -> ProcessResult:
        params = self._parse_processing_params(metadata)
        self._observer = build_observer(request_id, job_id, params)
        # on_pipeline_start opens the (debug-only) cv2 monkey-patch; flush()
        # closes it. Wrapping the whole pipeline in try/finally guarantees the
        # patch is restored even if early steps (QR detection, DB query,
        # template load) raise.
        self._observer.on_pipeline_start(metadata.get("processing_params", {}), params)
        try:
            # cv2 per-call spans are on by default (opt out with
            # TRACE_CV2=0); non-recording when OTel export is
            # unconfigured. Nested inside the stage spans opened by
            # _run_pipeline's _time() blocks.
            with trace_cv2_spans():
                return await self._run_pipeline(image, job_id, request_id, params)
        finally:
            self._observer.flush()

    async def _run_pipeline(self, image: cv2.typing.MatLike, job_id: UUID, request_id: UUID, params: ImageProcessingParams) -> ProcessResult:
        annotations_original: list[Annotations] = []
        annotations_warped: list[Annotations] = []
        template_thresh_task: asyncio.Task[np.ndarray] | None = None
        bubble_classifier: ResNet18BubbleClassifier | None = None
        bubble_classifier_load_error: str | None = None

        self._observer.on_input_scan(image)

        # Step 1: Detect QR codes
        with self._time("qrcode_detection"):
            # Detect primary QR code for exam identification
            _, annotations_qrcode, exam_round_id, area_id = self._detect_qrcode(image)
            # Detect all QR codes indexed by area_id for template rendering
            qrcode_map = self._detect_all_qrcodes(image)
        annotations_original.extend(annotations_qrcode)
        self._observer.on_qr_detected(exam_round_id, area_id, qrcode_map, annotations_qrcode)

        async with self.session_factory() as session:
            # Step 2: Get exam configuration from database
            async with self._time_async("database_queries"):
                exam_round, exam, exam_paper, paper_type, area, areas = await self._get_database_records(session, exam_round_id, area_id)

            # Step 3: Load template image
            async with self._time_async("template_load"):
                template_image, template_source_scale = await prepare_image(
                    self.client,
                    self.bucket_name,
                    exam_paper.id,
                    exam_paper.background_image,
                    "templates",
                    svg_min_render_width=params.svg_min_render_width,
                )
            self._observer.on_template_loaded(template_image)

            try:
                template_image, raster_to_recognition = self._resize_for_recognition(
                    template_image, params.recognition_max_width, params.recognition_scale
                )
                scan_image, scan_raster_to_recognition = self._resize_for_recognition(
                    image, params.recognition_max_width, params.recognition_scale
                )
                # ``recognition_scale`` is the user-unit ??recognition-pixel
                # multiplier consumed by ``_bubble_crop_bounds`` and the
                # QR-render path. For raster templates ``template_source_scale``
                # is 1.0, so this collapses to the prior raster-to-recognition
                # behavior. For SVG templates we may have rasterized at higher
                # resolution to give bubbles more pixels; ``template_source_scale``
                # carries that user-unit ??raster-pixel factor so area
                # coordinates (still in SVG user units) translate correctly
                # through the recognition resize.
                recognition_scale = template_source_scale * raster_to_recognition
                if abs(scan_raster_to_recognition - raster_to_recognition) > 1e-6:
                    await self._logger.warn(
                        f"[ProcessorV1] raster-to-recognition scales differ: "
                        f"template={raster_to_recognition:.4f}, scan={scan_raster_to_recognition:.4f}; "
                        f"using template scale"
                    )
                runtime_params = params.model_copy(update={"recognition_scale": recognition_scale})
                await self._logger.info(
                    f"[ProcessorV1] Recognition scale={recognition_scale:.4f} "
                    f"(source={template_source_scale:.4f} × raster_to_recog={raster_to_recognition:.4f}), "
                    f"template_width={template_image.shape[1]}, scan_width={scan_image.shape[1]}"
                )
                self._observer.on_resized(
                    template_image,
                    scan_image,
                    template_source_scale=template_source_scale,
                    raster_to_recognition=raster_to_recognition,
                    scan_raster_to_recognition=scan_raster_to_recognition,
                    recognition_scale=recognition_scale,
                    runtime_params=runtime_params,
                )

                # Step 3.4: Render TEXT areas onto the template (in place) before
                # binarization so the cached binarized template includes the same
                # text strokes the printed paper has — gives the matcher more
                # anchor strokes and aligns baseline_fill_map measurements.
                # Text rendering is an alignment aid, not a correctness
                # requirement — transient font/S3/file errors degrade to "no
                # text rendered" with a warning rather than aborting the scan
                # before alignment. Cancellation must still propagate.
                rendered_text_count = 0
                text_render_succeeded = True
                async with self._time_async("text_template_render"):
                    try:
                        rendered_text_count = await render_text_areas_on_template(
                            client=self.client,
                            bucket=self.bucket_name,
                            template_image=template_image,
                            areas=areas,
                            exam=exam,
                            exam_round=exam_round,
                            recognition_scale=recognition_scale,
                            logger=self._logger,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        text_render_succeeded = False
                        await self._logger.warn(
                            f"[ProcessorV1] TEXT rendering failed ({e!r}); continuing without rendered text"
                        )
                if rendered_text_count:
                    await self._logger.info(f"[ProcessorV1] Rendered {rendered_text_count} TEXT area(s) on template")
                self._observer.on_template_text_rendered(template_image, rendered_text_count)

                # Kick off template binarization against the pre-QR-render recognition template.
                # Cached by (exam_paper.id, exam_paper.updated_at, exam.id, exam.updated_at,
                # background_image, params); runs in parallel with QR rendering, alignment,
                # and warped binarization.
                template_thresh_task = asyncio.create_task(
                    self._get_or_binarize_template(
                        exam_paper, exam, exam_round, template_image, runtime_params, cacheable=text_render_succeeded
                    )
                )

                # Step 3.5: Render QR codes on template for better feature matching
                # Each QRCODE area is matched to its detected QR code by area_id
                qrcode_areas = [a for a in areas if a.area_type.base_type == "QRCODE"]
                async with self._time_async("qrcode_template_render"):
                    # Copy once up front so the in-flight binarization task keeps
                    # reading the original, untouched template. Subsequent renders
                    # mutate this copy in place instead of copying per-iteration.
                    if qrcode_areas:
                        template_image = template_image.copy()
                    for qrcode_area in qrcode_areas:
                        matched_barcode = qrcode_map.get(qrcode_area.id)
                        if matched_barcode is None:
                            await self._logger.warn(f"[ProcessorV1] No QR code detected for area {qrcode_area.id}")
                            continue

                        render_qrcode_on_template(
                            template_image,
                            barcode=matched_barcode,
                            pos_x=self._scale_position(qrcode_area.pos_x, recognition_scale),
                            pos_y=self._scale_position(qrcode_area.pos_y, recognition_scale),
                            width=self._scale_length(qrcode_area.width, recognition_scale),
                            height=self._scale_length(qrcode_area.height, recognition_scale),
                            inplace=True,
                        )
                        await self._logger.info(f"[ProcessorV1] Rendered QR code on template at ({qrcode_area.pos_x}, {qrcode_area.pos_y})")

                self._observer.on_template_qr_rendered(template_image)

                # Step 4: Align scan to template
                with self._time("alignment"):
                    warped_image, alignment_method, confidence = await self._align_scan_to_template(scan_image, template_image)

                await self._logger.info(f"[ProcessorV1] Alignment method: {alignment_method}, confidence: {confidence:.3f}")
                self._observer.on_aligned(warped_image, alignment_method, confidence)

                # Step 5: Binarize the warped image (template binarization kicked off earlier).
                # Warped binarization runs in a thread so the two complete in parallel.
                with self._time("binarization"):
                    warped_thresh, template_thresh = await asyncio.gather(
                        asyncio.to_thread(self._binarize_document, warped_image, runtime_params),
                        template_thresh_task,
                    )
                self._observer.on_binarized(warped_thresh, template_thresh)

                # Create output directory before starting parallel tasks
                os.makedirs(get_results_dir(request_id, job_id), exist_ok=True)

                # Step 6: Start save_images in background (doesn't depend on area_processing)
                # This runs in parallel with area_processing + annotate_images
                async def save_images_async() -> tuple[str, str]:
                    with self._time("save_images"):
                        return await asyncio.to_thread(
                            self._save_output_images, request_id, job_id, warped_thresh, warped_image
                        )

                save_task = asyncio.create_task(save_images_async())

                # Step 7: Process areas (filter by area_type.base_type)
                identifier_areas: list[ExamPaperArea] = [a for a in areas if a.area_type.base_type == "IDENTIFIER"]
                problem_areas: list[ExamPaperArea] = [a for a in areas if a.area_type.base_type == "PROBLEM"]
                option_areas: list[ExamPaperArea] = [a for a in areas if a.area_type.base_type == "OPTION"]
                metadata_areas: list[ExamPaperArea] = [a for a in areas if a.area_type.base_type == "METADATA"]
                bubble_areas = [*identifier_areas, *problem_areas, *option_areas, *metadata_areas]

                await self._logger.info(
                    f"[ProcessorV1] Measuring fill ratio with {runtime_params.bubble_measurement_shape} bubble ROI "
                    f"(bubble_padding_ratio={runtime_params.bubble_padding_ratio}, "
                    f"baseline_offset={runtime_params.baseline_fill_ratio_offset:.2f}, "
                    f"roi_morphology={runtime_params.bubble_roi_use_morphology})"
                )
                if runtime_params.use_bubble_classifier:
                    if not runtime_params.bubble_classifier_model_uri:
                        bubble_classifier_load_error = (
                            "[ProcessorV1] Bubble classifier enabled but bubble_classifier_model_uri is missing; "
                            "falling back to rule-based verdict."
                        )
                        await self._logger.warn(bubble_classifier_load_error)
                    else:
                        try:
                            bubble_classifier = await get_or_load_resnet18_bubble_classifier(
                                self.client, runtime_params.bubble_classifier_model_uri
                            )
                            await self._logger.info(
                                f"[ProcessorV1] Bubble classifier assist enabled: "
                                f"model_uri={runtime_params.bubble_classifier_model_uri}, "
                                f"threshold={float(runtime_params.bubble_classifier_threshold):.3f}, "
                                f"delta_margin={float(runtime_params.bubble_classifier_delta_margin):.3f}"
                            )
                        except Exception as exc:
                            bubble_classifier_load_error = (
                                f"[ProcessorV1] Failed to load bubble classifier from "
                                f"{runtime_params.bubble_classifier_model_uri}: {exc!r}. "
                                "Falling back to rule-based verdict."
                            )
                            await self._logger.warn(bubble_classifier_load_error)

                with self._time("area_processing"):
                    baseline_fill_map: dict[str, float] | None = None
                    if runtime_params.use_template_baseline_fill_delta:
                        baseline_fill_map = await self._get_or_compute_template_baseline_fill_map(
                            exam_paper,
                            exam,
                            exam_round,
                            template_thresh,
                            bubble_areas,
                            runtime_params,
                            cacheable=text_render_succeeded,
                        )
                    if baseline_fill_map is not None:
                        self._observer.on_baseline_fill_map(baseline_fill_map)

                    student_info_results = self._process_child_areas(
                        warped_thresh,
                        template_thresh,
                        identifier_areas,
                        request_id,
                        job_id,
                        runtime_params,
                        baseline_fill_map,
                        bubble_classifier,
                        bubble_classifier_load_error,
                    )
                    problem_results = self._process_child_areas(
                        warped_thresh,
                        template_thresh,
                        problem_areas,
                        request_id,
                        job_id,
                        runtime_params,
                        baseline_fill_map,
                        bubble_classifier,
                        bubble_classifier_load_error,
                    )
                    option_results = self._process_child_areas(
                        warped_thresh,
                        template_thresh,
                        option_areas,
                        request_id,
                        job_id,
                        runtime_params,
                        baseline_fill_map,
                        bubble_classifier,
                        bubble_classifier_load_error,
                    )
                    metadata_results_raw = self._process_child_areas(
                        warped_thresh,
                        template_thresh,
                        metadata_areas,
                        request_id,
                        job_id,
                        runtime_params,
                        baseline_fill_map,
                        bubble_classifier,
                        bubble_classifier_load_error,
                    )

                area_image_paths: dict[str, str] = {}
                area_image_paths.update(student_info_results[2])
                area_image_paths.update(problem_results[2])
                area_image_paths.update(option_results[2])
                area_image_paths.update(metadata_results_raw[2])

                area_metrics: dict[str, AreaMetrics] = {}
                area_metrics.update(student_info_results[3])
                area_metrics.update(problem_results[3])
                area_metrics.update(option_results[3])
                area_metrics.update(metadata_results_raw[3])

                annotations_warped.extend(student_info_results[0])
                annotations_warped.extend(problem_results[0])
                annotations_warped.extend(option_results[0])
                annotations_warped.extend(metadata_results_raw[0])

                # METADATA areas don't have an associated ExamProblem, so the
                # detected localIds are keyed by ExamPaperArea.id (vs. area.index
                # for the other three) — scan.py joins them to choice_type via
                # the area itself rather than via a remap table.
                metadata_area_by_index = {a.index: a for a in metadata_areas}
                metadata_results: dict[UUID, list[str]] = {
                    metadata_area_by_index[idx].id: local_ids
                    for idx, local_ids in metadata_results_raw[1].items()
                    if idx in metadata_area_by_index
                }

                # Annotations are already in template coordinates (warped space)
                annotations_cropped = annotations_warped

                with self._time("annotate_images"):
                    # Annotate warped image with detected areas
                    warped_annotated = self._annotated_image(warped_image, annotations_warped, params)
                    annotated_cropped_path = get_result_path(request_id, job_id, "annotated_cropped.png")
                    cv2.imwrite(annotated_cropped_path, cv2.cvtColor(warped_annotated, cv2.COLOR_RGB2BGR))
                self._observer.on_warped_annotated(warped_annotated)
                self._observer.on_results(
                    area_metrics,
                    student_info_results[1],
                    problem_results[1],
                    option_results[1],
                    metadata_results,
                )

                # Wait for save_images to complete
                threshold_path, flattened_path = await save_task

                return ProcessResult(
                    organization_id=exam.organization_id,
                    exam_id=exam.id,
                    exam_round_id=exam_round_id,
                    annotations=annotations_original,  # Original image annotations
                    annotations_cropped=annotations_cropped,  # Warped image annotations
                    image_annotated_cropped_path=annotated_cropped_path,
                    image_flattened_path=flattened_path,
                    image_threshold_path=threshold_path,
                    area_image_paths=area_image_paths,
                    area_metrics=area_metrics,
                    student_info_results=student_info_results[1],
                    problem_results=problem_results[1],
                    option_results=option_results[1],
                    metadata_results=metadata_results,
                    processing_params=runtime_params,
                    processing_meta=ProcessingMeta(bubble_shape=runtime_params.bubble_measurement_shape),
                )
            finally:
                # Cancel if still running, then always drain to retrieve any
                # exception. Covers three cases:
                # (a) happy path ??gather already consumed the task (await is a no-op).
                # (b) error before gather, task still running ??cancel + drain.
                # (c) error before gather, task already completed with an exception ??
                #     done() guard would skip draining and leave the exception
                #     unretrieved, so the await must be unconditional.
                if template_thresh_task is not None and not template_thresh_task.done():
                    template_thresh_task.cancel()
                try:
                    if template_thresh_task is not None:
                        await template_thresh_task
                except asyncio.CancelledError:
                    # Re-raise when our enclosing task is itself being cancelled
                    # (shutdown/timeout) ??otherwise we'd swallow the signal.
                    # Suppress only the CancelledError we triggered above.
                    current = asyncio.current_task()
                    if current is not None and current.cancelling() > 0:
                        raise
                except Exception:
                    pass

    async def _align_scan_to_template(
        self,
        scan_image: np.ndarray,
        template_image: np.ndarray,
    ) -> tuple[np.ndarray, str, float]:
        """Align scan image to template using RoMaV2.

        RoMaV2 uses dense warp fields (not homography) to handle non-planar
        deformations like curved pages and wrinkles.

        Returns:
            Tuple of (warped_image, method, confidence).
        """
        await self._logger.info("[ProcessorV1] Attempting RoMaV2 dense warp alignment")

        if not self._matcher._initialized and not self._matcher.initialize():
            raise ProcessError("RoMaV2 matcher failed to initialize", code="ROMAV2_INITIALIZATION_FAILED")

        result = self._matcher.warp_scan_to_template(scan_image, template_image)
        if result is None:
            raise ProcessError("RoMaV2 alignment failed", code="ROMAV2_ALIGNMENT_FAILED")

        warped, match_result = result
        confidence = float(match_result.confidence)
        await self._logger.info(f"[ProcessorV1] RoMaV2 alignment confidence: {confidence:.3f}")
        if not np.isfinite(confidence):
            raise ProcessError(
                f"RoMaV2 alignment confidence is not finite: {confidence}",
                code="ROMAV2_NON_FINITE_CONFIDENCE",
                params={"confidence": str(confidence)},
            )
        if confidence <= ROMAV2_MIN_CONFIDENCE:
            raise ProcessError(
                f"RoMaV2 alignment confidence below threshold: {confidence:.3f}",
                code="ROMAV2_LOW_CONFIDENCE",
                params={"confidence": confidence, "threshold": ROMAV2_MIN_CONFIDENCE},
            )

        return warped, "romav2_dense", confidence
