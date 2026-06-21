import cv2
import numpy as np
import logging
import os
from typing import List, Dict, Any, Tuple

# Fix for Windows username encoding issue in C++ backend
os.environ["USERPROFILE"] = r"C:\dev\paddle_models"
# Disable MKL-DNN to prevent fused_conv2d error on Windows Paddle 2.6+
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_mkldnn_bfloat16"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

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
            # lang='korean' includes korean and english/numbers
            self.ocr = PaddleOCR(use_angle_cls=True, lang='korean', show_log=False, use_mkldnn=False)
            
    def manual_crop_and_ocr(self, image_path: str, crop_rect: Tuple[int, int, int, int] = None, preprocess: bool = False) -> List[Dict[str, Any]]:
        """
        주어진 이미지에서 특정 영역(crop_rect=(x, y, w, h))을 수동으로 잘라내어 OCR을 수행합니다.
        preprocess가 True이면 OpenCV Baseline을 적용해 라벨을 추출하고 대비를 높입니다.
        """
        if self.ocr is None:
            raise RuntimeError("PaddleOCR engine not initialized.")
            
        # Use cv2.imdecode instead of cv2.imread to handle Korean path correctly
        img_array = np.fromfile(image_path, np.uint8)
        if img_array.size == 0:
            raise FileNotFoundError(f"Image not found: {image_path}")
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
        if crop_rect:
            x, y, w, h = crop_rect
            cropped = img[y:y+h, x:x+w]
        else:
            x, y = 0, 0
            cropped = img
            
        if preprocess:
            from worker.services.opencv_baseline import extract_label_from_spine
            cropped = extract_label_from_spine(cropped)
            # The resulting image is already cropped further inside the spine bounding box.
            # However, for simplicity of bounding box mapping, we just pass the original box mapping.
        
        # Run OCR
        result = self.ocr.ocr(cropped, cls=True)
        print("Raw OCR result:", result)
        
        extracted = []
        if result and result[0]:
            for line in result[0]:
                bbox = line[0] # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = line[1][0]
                confidence = line[1][1]
                
                # 원본 이미지 기준의 좌표로 보정
                original_bbox = []
                for pt in bbox:
                    original_bbox.append([pt[0] + x, pt[1] + y])
                    
                extracted.append({
                    "text": text,
                    "confidence": confidence,
                    "bbox": original_bbox
                })
                
        return extracted

# Singleton instance
vision_service = VisionService()
