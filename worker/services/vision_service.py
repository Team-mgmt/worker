import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keep Paddle/Matplotlib caches in the project workspace. This avoids Windows
# username encoding and home-directory permission issues during local demos.
PROJECT_CACHE_DIR = os.path.abspath(os.path.join(os.getcwd(), ".paddle_cache"))
os.environ["USERPROFILE"] = PROJECT_CACHE_DIR
os.environ["PADDLE_HOME"] = os.path.join(PROJECT_CACHE_DIR, "paddle")
os.environ["MPLCONFIGDIR"] = os.path.join(PROJECT_CACHE_DIR, "matplotlib")
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"
os.environ["FLAGS_use_mkldnn_bfloat16"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

import cv2
import numpy as np

from worker.core.config import settings

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CropMetadata:
    method: str
    size: list[int]
    path: str | None = None
    ocr_variant: str = "original"
    attempt_count: int = 1
    label_text: str | None = None
    label_confidence: float | None = None


class VisionService:
    def __init__(self, device: str | None = None):
        if PaddleOCR is None:
            logger.warning("PaddleOCR is not installed. Vision Service will not work properly.")
            self.ocr = None
        else:
            os.makedirs(PROJECT_CACHE_DIR, exist_ok=True)
            self.ocr = PaddleOCR(
                lang="korean",
                device=device or os.getenv("PADDLE_OCR_DEVICE", "cpu"),
                text_detection_model_name=os.getenv(
                    "PADDLE_OCR_DETECTION_MODEL",
                    "PP-OCRv5_mobile_det",
                ),
                text_recognition_model_name=os.getenv(
                    "PADDLE_OCR_RECOGNITION_MODEL",
                    "korean_PP-OCRv5_mobile_rec",
                ),
                enable_mkldnn=False,
                cpu_threads=1,
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )

    def manual_crop_and_ocr(
        self,
        image_path: str,
        crop_rect: tuple[int, int, int, int] | None = None,
        preprocess: bool = False,
    ) -> list[dict[str, Any]]:
        extracted, _ = self.crop_and_ocr(
            image_path,
            crop_rect=crop_rect,
            preprocess=preprocess,
        )
        return extracted

    def crop_and_ocr(
        self,
        image_path: str,
        crop_rect: tuple[int, int, int, int] | None = None,
        obb_polygon: list[list[float]] | None = None,
        preprocess: bool = False,
        crop_output_path: str | None = None,
        adaptive: bool = True,
        force_fallback: bool = False,
    ) -> tuple[list[dict[str, Any]], CropMetadata]:
        if self.ocr is None:
            raise RuntimeError("PaddleOCR engine not initialized.")

        img_array = np.fromfile(image_path, np.uint8)
        if img_array.size == 0:
            raise FileNotFoundError(f"Image not found: {image_path}")
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        method = "full_image"
        if obb_polygon and len(obb_polygon) == 4:
            cropped = self._rectify_obb(img, obb_polygon)
            x, y = 0, 0
            method = "obb_perspective"
        elif crop_rect:
            x, y, w, h = crop_rect
            cropped = img[y : y + h, x : x + w]
            method = "axis_aligned"
        else:
            x, y = 0, 0
            cropped = img

        if cropped.size == 0:
            raise ValueError("The detected crop is empty.")

        if preprocess:
            from worker.services.opencv_baseline import extract_label_from_spine

            cropped = extract_label_from_spine(cropped)

        saved_path = None
        if crop_output_path:
            output_path = Path(crop_output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            success, encoded = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not success:
                raise ValueError("Failed to encode the OCR crop.")
            encoded.tofile(output_path)
            saved_path = str(output_path)

        extracted, diagnostics = self._adaptive_ocr(
            cropped,
            adaptive=adaptive,
            force_fallback=force_fallback,
        )
        metadata = CropMetadata(
            method=method,
            size=[int(cropped.shape[1]), int(cropped.shape[0])],
            path=saved_path,
            ocr_variant=diagnostics["variant"],
            attempt_count=diagnostics["attempt_count"],
            label_text=diagnostics["label_text"],
            label_confidence=diagnostics["label_confidence"],
        )
        return self._offset_results(extracted, x, y), metadata

    def crop_many_for_fast_ocr(
        self,
        image_path: str,
        crop_specs: list[tuple[tuple[int, int, int, int], list[list[float]] | None]],
        crop_output_paths: list[str | None] | None = None,
    ) -> tuple[list[list[dict[str, Any]]], list[CropMetadata]]:
        """OCR spine crops in contact sheets while preserving their input order."""

        if self.ocr is None:
            raise RuntimeError("PaddleOCR engine not initialized.")

        image = self._load_image(image_path)
        crops: list[np.ndarray] = []
        metadata: list[CropMetadata] = []
        for index, (crop_rect, polygon) in enumerate(crop_specs):
            cropped, method = self._extract_crop(image, crop_rect, polygon)
            crops.append(cropped)
            saved_path = None
            if crop_output_paths and index < len(crop_output_paths) and crop_output_paths[index]:
                output_path = Path(crop_output_paths[index] or "")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                success, encoded = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 92])
                if not success:
                    raise ValueError("Failed to encode the OCR crop.")
                encoded.tofile(output_path)
                saved_path = str(output_path)
            metadata.append(
                CropMetadata(
                    method=method,
                    size=[int(cropped.shape[1]), int(cropped.shape[0])],
                    path=saved_path,
                    ocr_variant="contact_sheet",
                    attempt_count=1,
                )
            )

        grouped: list[list[dict[str, Any]]] = [[] for _ in crops]
        batch_size = max(1, settings.OCR_CONTACT_SHEET_BATCH_SIZE)
        for start in range(0, len(crops), batch_size):
            batch = crops[start : start + batch_size]
            sheet, ranges = self._compose_contact_sheet(batch)
            extracted = self._run_ocr(sheet)
            distributed = self._distribute_contact_sheet_results(extracted, ranges)
            grouped[start : start + len(batch)] = distributed

        return grouped, metadata

    @staticmethod
    def _load_image(image_path: str) -> np.ndarray:
        img_array = np.fromfile(image_path, np.uint8)
        if img_array.size == 0:
            raise FileNotFoundError(f"Image not found: {image_path}")
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Failed to decode image: {image_path}")
        return image

    @staticmethod
    def _extract_crop(
        image: np.ndarray,
        crop_rect: tuple[int, int, int, int],
        obb_polygon: list[list[float]] | None,
    ) -> tuple[np.ndarray, str]:
        if obb_polygon and len(obb_polygon) == 4:
            cropped = VisionService._rectify_obb(image, obb_polygon)
            method = "obb_perspective"
        else:
            x, y, width, height = crop_rect
            cropped = image[y : y + height, x : x + width]
            method = "axis_aligned"
        if cropped.size == 0:
            raise ValueError("The detected crop is empty.")
        return cropped, method

    @staticmethod
    def _compose_contact_sheet(crops: list[np.ndarray]) -> tuple[np.ndarray, list[tuple[int, int]]]:
        gutter = max(0, settings.OCR_CONTACT_SHEET_GUTTER)
        height = max(crop.shape[0] for crop in crops)
        width = sum(crop.shape[1] for crop in crops) + gutter * max(0, len(crops) - 1)
        sheet = np.full((height, width, 3), 255, dtype=np.uint8)
        ranges: list[tuple[int, int]] = []
        offset = 0
        for crop in crops:
            end = offset + crop.shape[1]
            sheet[: crop.shape[0], offset:end] = crop
            ranges.append((offset, end))
            offset = end + gutter
        return sheet, ranges

    @staticmethod
    def _distribute_contact_sheet_results(
        extracted: list[dict[str, Any]],
        ranges: list[tuple[int, int]],
    ) -> list[list[dict[str, Any]]]:
        grouped: list[list[dict[str, Any]]] = [[] for _ in ranges]
        for item in extracted:
            bbox = item.get("bbox") or []
            if not bbox:
                continue
            center_x = sum(float(point[0]) for point in bbox) / len(bbox)
            for index, (start, end) in enumerate(ranges):
                if start <= center_x < end:
                    copied = dict(item)
                    copied["bbox"] = [[float(point[0]) - start, float(point[1])] for point in bbox]
                    grouped[index].append(copied)
                    break
        return grouped

    def _adaptive_ocr(
        self,
        cropped: np.ndarray,
        *,
        adaptive: bool = True,
        force_fallback: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidates: list[tuple[str, list[dict[str, Any]]]] = []

        primary = self._run_ocr(cropped)
        candidates.append(("original", primary))

        primary_text = self._join_text(primary)
        primary_confidence = self._average_confidence(primary) or 0.0
        needs_fallback = (
            adaptive
            and settings.OCR_ENABLE_ADAPTIVE_FALLBACK
            and (
                force_fallback
                or primary_confidence < settings.OCR_FALLBACK_CONFIDENCE
                or not self._has_call_number(primary_text)
            )
        )

        label_result: list[dict[str, Any]] = []
        label_text = ""
        label_confidence = None
        label_attempted = False

        if needs_fallback:
            # The previous implementation ran this second OCR pass for every
            # spine. Most clear shelf images already expose the call number in
            # the primary pass, so defer the label-region pass until fallback
            # evidence is actually needed.
            label_image = self._prepare_label_region(cropped)
            label_attempted = True
            label_result = self._run_ocr(label_image)
            label_text = self._join_text(label_result)
            label_confidence = self._average_confidence(label_result)

            variants = [
                ("clahe_sharpen", self._enhance_for_ocr(cropped)),
                ("rotate_90", cv2.rotate(cropped, cv2.ROTATE_90_CLOCKWISE)),
                ("rotate_270", cv2.rotate(cropped, cv2.ROTATE_90_COUNTERCLOCKWISE)),
            ]
            for name, image in variants[: max(0, settings.OCR_MAX_FALLBACK_VARIANTS)]:
                candidates.append((name, self._run_ocr(image)))

        candidate_score = self._text_candidate_score if force_fallback else self._candidate_score
        variant, best = max(candidates, key=lambda item: candidate_score(item[1]))
        best_text = self._join_text(best)
        if label_text and self._has_call_number(label_text) and label_text not in best_text:
            best = [*best, *label_result]
            variant = f"{variant}+label"

        return best, {
            "variant": variant,
            "attempt_count": len(candidates) + (1 if label_attempted else 0),
            "label_text": label_text or None,
            "label_confidence": label_confidence,
        }

    def _run_ocr(self, image: np.ndarray) -> list[dict[str, Any]]:
        return self._parse_ocr_result(self.ocr.ocr(image), 0, 0)

    @staticmethod
    def _prepare_label_region(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        ratio = min(0.6, max(0.2, settings.OCR_LABEL_REGION_RATIO))
        label = image[max(0, int(height * (1.0 - ratio))) : height, :]
        target_width = max(width, settings.OBB_CROP_MIN_WIDTH)
        scale = target_width / max(1, width)
        label = cv2.resize(label, (target_width, max(1, round(label.shape[0] * scale))), interpolation=cv2.INTER_CUBIC)
        return VisionService._enhance_for_ocr(label)

    @staticmethod
    def _enhance_for_ocr(image: np.ndarray) -> np.ndarray:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(lightness)
        enhanced = cv2.cvtColor(cv2.merge((lightness, channel_a, channel_b)), cv2.COLOR_LAB2BGR)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
        return cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)

    @staticmethod
    def _join_text(extracted: list[dict[str, Any]]) -> str:
        return " ".join(str(item.get("text", "")).strip() for item in extracted if str(item.get("text", "")).strip())

    @staticmethod
    def _average_confidence(extracted: list[dict[str, Any]]) -> float | None:
        values = [float(item["confidence"]) for item in extracted if item.get("confidence") is not None]
        return sum(values) / len(values) if values else None

    @staticmethod
    def _has_call_number(text: str) -> bool:
        import re

        return bool(re.search(r"(?<!\d)\d{3}(?:[.,:]\d+)?\s+[^\s]*\d+", text))

    @classmethod
    def _candidate_score(cls, extracted: list[dict[str, Any]]) -> tuple[int, float, int]:
        text = cls._join_text(extracted)
        confidence = cls._average_confidence(extracted) or 0.0
        return (1 if cls._has_call_number(text) else 0, confidence, len(text))

    @classmethod
    def _text_candidate_score(cls, extracted: list[dict[str, Any]]) -> tuple[int, float, int]:
        """Prefer title-bearing text for a target-search precision retry."""

        text = cls._join_text(extracted)
        confidence = cls._average_confidence(extracted) or 0.0
        return (len(text), confidence, 1 if cls._has_call_number(text) else 0)

    @staticmethod
    def _offset_results(extracted: list[dict[str, Any]], offset_x: int, offset_y: int) -> list[dict[str, Any]]:
        if not offset_x and not offset_y:
            return extracted
        adjusted = []
        for item in extracted:
            copied = dict(item)
            copied["bbox"] = [
                [float(point[0]) + offset_x, float(point[1]) + offset_y]
                for point in item.get("bbox", [])
            ]
            adjusted.append(copied)
        return adjusted

    @staticmethod
    def _rectify_obb(image: np.ndarray, polygon: list[list[float]]) -> np.ndarray:
        points = np.asarray(polygon, dtype=np.float32)
        center = points.mean(axis=0)
        padding_scale = 1.0 + (2.0 * max(0.0, settings.OBB_CROP_PADDING_RATIO))
        points = center + ((points - center) * padding_scale)
        points[:, 0] = np.clip(points[:, 0], 0, image.shape[1] - 1)
        points[:, 1] = np.clip(points[:, 1], 0, image.shape[0] - 1)

        ordered = VisionService._order_quad(points)
        top_left, top_right, bottom_right, bottom_left = ordered
        width = max(
            np.linalg.norm(bottom_right - bottom_left),
            np.linalg.norm(top_right - top_left),
        )
        height = max(
            np.linalg.norm(top_right - bottom_right),
            np.linalg.norm(top_left - bottom_left),
        )
        target_width = max(1, int(round(width)))
        target_height = max(1, int(round(height)))
        destination = np.asarray(
            [
                [0, 0],
                [target_width - 1, 0],
                [target_width - 1, target_height - 1],
                [0, target_height - 1],
            ],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(ordered, destination)
        cropped = cv2.warpPerspective(
            image,
            matrix,
            (target_width, target_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        if cropped.shape[1] > cropped.shape[0]:
            cropped = cv2.rotate(cropped, cv2.ROTATE_90_CLOCKWISE)

        width = cropped.shape[1]
        height = cropped.shape[0]
        scale = max(1.0, settings.OBB_CROP_MIN_WIDTH / max(1, width))
        scale = min(scale, settings.OBB_CROP_MAX_EDGE / max(width, height))
        if abs(scale - 1.0) > 0.01:
            cropped = cv2.resize(
                cropped,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
            )
        return cropped

    @staticmethod
    def _order_quad(points: np.ndarray) -> np.ndarray:
        ordered = np.zeros((4, 2), dtype=np.float32)
        coordinate_sum = points.sum(axis=1)
        coordinate_difference = np.diff(points, axis=1).reshape(-1)
        ordered[0] = points[np.argmin(coordinate_sum)]
        ordered[2] = points[np.argmax(coordinate_sum)]
        ordered[1] = points[np.argmin(coordinate_difference)]
        ordered[3] = points[np.argmax(coordinate_difference)]
        return ordered

    def _parse_ocr_result(self, result: Any, offset_x: int, offset_y: int) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        if not result:
            return extracted

        first_result = result[0] if isinstance(result, list) else result

        if isinstance(first_result, dict) or hasattr(first_result, "get"):
            texts = first_result.get("rec_texts") or []
            scores = first_result.get("rec_scores") or []
            boxes = first_result.get("rec_polys") or first_result.get("dt_polys") or []

            for index, text in enumerate(texts):
                text = str(text).strip()
                if not text:
                    continue

                bbox = boxes[index] if index < len(boxes) else []
                original_bbox = [
                    [float(pt[0]) + offset_x, float(pt[1]) + offset_y]
                    for pt in bbox
                ]
                extracted.append(
                    {
                        "text": text,
                        "confidence": float(scores[index]) if index < len(scores) else None,
                        "bbox": original_bbox,
                    }
                )
            return extracted

        if isinstance(first_result, list):
            for line in first_result:
                bbox = line[0]
                text = str(line[1][0]).strip()
                if not text:
                    continue
                confidence = line[1][1]
                original_bbox = [[pt[0] + offset_x, pt[1] + offset_y] for pt in bbox]
                extracted.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "bbox": original_bbox,
                    }
                )

        return extracted


vision_service = VisionService()
