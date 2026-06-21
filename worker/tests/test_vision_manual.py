import pytest
import os
from worker.services.vision_service import vision_service

def test_manual_crop_ocr():
    # 실제 서가 사진 (Artifact path)
    img_path = r"C:\Users\임준수\.gemini\antigravity-ide\brain\08611e93-63e8-4264-8339-a59b8b99f699\media__1781075116056.png"
    
    # 1. 원본 이미지 전체에서 OCR 텍스트 추출 확인 (수동 Crop 전)
    # 실제 구현시엔 crop_rect를 (x, y, w, h)로 전달
    # 여기서는 데모를 위해 적당한 하단 영역을 지정해봄
    
    if not os.path.exists(img_path):
        pytest.skip(f"Image not found at {img_path}")
        
    # x, y, width, height (임의 하단 영역 - 테스트용)
    crop_rect = None
    
    results = vision_service.manual_crop_and_ocr(img_path, crop_rect)
    print("OCR Results in cropped area:")
    for res in results:
        print(f"- Text: {res['text']}, Confidence: {res['confidence']:.2f}")
        
    assert len(results) > 0
