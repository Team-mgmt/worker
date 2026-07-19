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
    def __init__(self):
        if PaddleOCR is None:
            logger.warning("PaddleOCR is not installed. Vision Service will not work properly.")
            self.ocr = None
        else:
            os.makedirs(PROJECT_CACHE_DIR, exist_ok=True)
            self.ocr = PaddleOCR(
                lang="korean",
                device="cpu",
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

        extracted, diagnostics = self._adaptive_ocr(cropped)
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

    def _adaptive_ocr(self, cropped: np.ndarray) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidates: list[tuple[str, list[dict[str, Any]]]] = []

        primary = self._run_ocr(cropped)
        candidates.append(("original", primary))

        # Shelf labels contain the strongest matching key. Always inspect the
        # lower region independently so title text cannot suppress small labels.
        label_image = self._prepare_label_region(cropped)
        label_result = self._run_ocr(label_image)
        label_text = self._join_text(label_result)
        label_confidence = self._average_confidence(label_result)

        primary_text = self._join_text(primary)
        primary_confidence = self._average_confidence(primary) or 0.0
        needs_fallback = (
            settings.OCR_ENABLE_ADAPTIVE_FALLBACK
            and (primary_confidence < settings.OCR_FALLBACK_CONFIDENCE or not self._has_call_number(primary_text))
        )

        if needs_fallback:
            variants = [
                ("clahe_sharpen", self._enhance_for_ocr(cropped)),
                ("rotate_90", cv2.rotate(cropped, cv2.ROTATE_90_CLOCKWISE)),
                ("rotate_270", cv2.rotate(cropped, cv2.ROTATE_90_COUNTERCLOCKWISE)),
            ]
            for name, image in variants[: max(0, settings.OCR_MAX_FALLBACK_VARIANTS)]:
                candidates.append((name, self._run_ocr(image)))

        variant, best = max(candidates, key=lambda item: self._candidate_score(item[1]))
        best_text = self._join_text(best)
        if label_text and self._has_call_number(label_text) and label_text not in best_text:
            best = [*best, *label_result]
            variant = f"{variant}+label"

        return best, {
            "variant": variant,
            "attempt_count": len(candidates) + 1,
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
