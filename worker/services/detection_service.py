from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


DEFAULT_MODEL_PATH = "worker/models/book_spine_run/weights/best.pt"


@dataclass(frozen=True)
class SpineDetection:
    bbox: tuple[int, int, int, int]
    confidence: float | None
    polygon: list[list[float]]
    is_obb: bool = False


class BookSpineDetector:
    def __init__(self, model_path: str | None = None):
        model_path = model_path or os.getenv("BOOK_SPINE_YOLO_MODEL_PATH", DEFAULT_MODEL_PATH)
        self.model_path = os.path.abspath(model_path)

        if YOLO is None:
            self.model = None
            print("Warning: ultralytics is not installed.")
        elif not os.path.exists(self.model_path):
            self.model = None
            print(f"Warning: YOLO model not found at {self.model_path}.")
        else:
            self.model = YOLO(self.model_path)

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def detect_spines(self, image_path: str, conf_threshold: float = 0.5) -> list[SpineDetection]:
        """Detect book spines while preserving confidence and OBB geometry."""
        if self.model is None:
            raise RuntimeError(f"YOLO model is not loaded. Expected model at {self.model_path}.")

        results = self.model(image_path, conf=conf_threshold)

        detections: list[SpineDetection] = []
        if results:
            result = results[0]
            if result.obb is not None:
                xyxy_rows = result.obb.xyxy.cpu().numpy()
                polygon_rows = result.obb.xyxyxyxy.cpu().numpy()
                confidence_rows = result.obb.conf.cpu().numpy()
                for xyxy, polygon, confidence in zip(xyxy_rows, polygon_rows, confidence_rows, strict=True):
                    detections.append(self._to_detection(xyxy, polygon, float(confidence), is_obb=True))
            elif result.boxes is not None:
                xyxy_rows = result.boxes.xyxy.cpu().numpy()
                confidence_rows = result.boxes.conf.cpu().numpy()
                for xyxy, confidence in zip(xyxy_rows, confidence_rows, strict=True):
                    x1, y1, x2, y2 = (float(value) for value in xyxy)
                    polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                    detections.append(self._to_detection(xyxy, polygon, float(confidence), is_obb=False))

        detections.sort(key=lambda detection: detection.bbox[0])
        return detections

    @staticmethod
    def _to_detection(xyxy, polygon, confidence: float | None, *, is_obb: bool = False) -> SpineDetection:
        x1, y1, x2, y2 = (float(value) for value in xyxy)
        return SpineDetection(
            bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
            confidence=confidence,
            polygon=[[float(point[0]), float(point[1])] for point in polygon],
            is_obb=is_obb,
        )


detector_service = BookSpineDetector()
