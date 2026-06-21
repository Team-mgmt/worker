import os
import cv2
import numpy as np
from typing import List, Tuple
try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

class BookSpineDetector:
    def __init__(self, model_path: str = "worker/models/book_spine_run/weights/best.pt"):
        self.model_path = os.path.abspath(model_path)
        if YOLO is None:
            self.model = None
            print("Warning: ultralytics is not installed.")
        elif not os.path.exists(self.model_path):
            self.model = None
            print(f"Warning: YOLO model not found at {self.model_path}. Please train the model first.")
        else:
            self.model = YOLO(self.model_path)
            
    def detect_spines(self, image_path: str, conf_threshold: float = 0.5) -> List[Tuple[int, int, int, int]]:
        """
        주어진 이미지에서 책등(book_spine)의 BBox 목록을 추출하고,
        왼쪽에서 오른쪽으로 정렬하여 반환합니다.
        반환 형태: [(x, y, w, h), ...]
        """
        if self.model is None:
            raise RuntimeError("YOLO model is not loaded. Cannot perform detection.")
            
        # Run inference
        results = self.model(image_path, conf=conf_threshold)
        
        bboxes = []
        if len(results) > 0:
            result = results[0]
            boxes = result.boxes
            for box in boxes:
                # box.xyxy[0] returns [x1, y1, x2, y2]
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
                bboxes.append((x, y, w, h))
                
        # Sort left to right based on x coordinate
        bboxes.sort(key=lambda b: b[0])
        return bboxes

# Singleton instance for easy import
detector_service = BookSpineDetector()
