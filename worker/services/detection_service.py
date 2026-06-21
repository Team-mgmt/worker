from __future__ import annotations

import os
from typing import List, Tuple

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


DEFAULT_MODEL_PATH = "worker/models/book_spine_run/weights/best.pt"


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

    def detect_spines(self, image_path: str, conf_threshold: float = 0.5) -> List[Tuple[int, int, int, int]]:
        """Detect book-spine boxes and return [(x, y, width, height), ...]."""
        if self.model is None:
            raise RuntimeError(f"YOLO model is not loaded. Expected model at {self.model_path}.")

        results = self.model(image_path, conf=conf_threshold)

        bboxes: list[tuple[int, int, int, int]] = []
        if results:
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                bboxes.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))

        bboxes.sort(key=lambda bbox: bbox[0])
        return bboxes


detector_service = BookSpineDetector()
