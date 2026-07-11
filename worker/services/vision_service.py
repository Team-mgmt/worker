import logging
import os
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

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

logger = logging.getLogger(__name__)


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
        if self.ocr is None:
            raise RuntimeError("PaddleOCR engine not initialized.")

        img_array = np.fromfile(image_path, np.uint8)
        if img_array.size == 0:
            raise FileNotFoundError(f"Image not found: {image_path}")
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if crop_rect:
            x, y, w, h = crop_rect
            cropped = img[y : y + h, x : x + w]
        else:
            x, y = 0, 0
            cropped = img

        if preprocess:
            from worker.services.opencv_baseline import extract_label_from_spine

            cropped = extract_label_from_spine(cropped)

        result = self.ocr.ocr(cropped)
        return self._parse_ocr_result(result, x, y)

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
