import sys
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from fastapi.testclient import TestClient
from worker.api.server import app

client = TestClient(app)

def test_inference_demo_scenario():
    mock_payload = {
      "library_code": "111058",
      "room_name": "노원중앙종합자료실",
      "source_name": "nowon_shelf_demo_001.jpg",
      "ocr_results": [
        {
          "detected_order": 1,
          "raw_text": "지우전 813.6 박62ㅈ",
          "title": "지우전",
          "author": None,
          "call_number": "813.6 박62ㅈ",
          "bbox": [90, 90, 190, 910],
          "ocr_confidence": 0.91
        },
        {
          "detected_order": 2,
          "raw_text": "나비사냥 SEASON 2 813.6 박64ㄴ v.2",
          "title": "나비사냥 SEASON 2",
          "author": "박영광",
          "call_number": "813.6 박64ㄴ v.2",
          "bbox": [390, 80, 485, 910],
          "ocr_confidence": 0.94
        },
        {
          "detected_order": 3,
          "raw_text": "폴리스 813.6 박67ㅍ",
          "title": "폴리스",
          "author": None,
          "call_number": "813.6 박67ㅍ",
          "bbox": [480, 80, 570, 910],
          "ocr_confidence": 0.90
        },
        {
          "detected_order": 4,
          "raw_text": "러브 어게인 813.6 박64ㄹ",
          "title": "러브 어게인",
          "author": "박영",
          "call_number": "813.6 박64ㄹ",
          "bbox": [680, 70, 780, 910],
          "ocr_confidence": 0.95
        },
        {
          "detected_order": 5,
          "raw_text": "못된 정신의 확산 813.6 박64ㅁ",
          "title": "못된 정신의 확산",
          "author": "박영광",
          "call_number": "813.6 박64ㅁ",
          "bbox": [775, 70, 880, 910],
          "ocr_confidence": 0.91
        },
        {
          "detected_order": 6,
          "raw_text": "지상의 방 한 칸 813.6 박64ㅈ",
          "title": "지상의 방 한 칸",
          "author": None,
          "call_number": "813.6 박64ㅈ",
          "bbox": [1060, 65, 1160, 910],
          "ocr_confidence": 0.93
        },
        {
          "detected_order": 7,
          "raw_text": "영어로 영어를 가르치자 740 황19ㅇ",
          "title": "영어로 영어를 가르치자!",
          "author": None,
          "call_number": "740 황19ㅇ",
          "bbox": [1260, 60, 1360, 930],
          "ocr_confidence": 0.98
        }
      ]
    }
    
    response = client.post("/inference/scan", json=mock_payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "session_id" in data
    assert len(data["results"]) == 7
    
    est = data["estimated_shelf"]
    assert est["kdc_start"] == 810.0
    assert est["kdc_end"] == 819.99
    assert est["dominant_class"] == "813.6"
    assert est["confidence"] > 0.8
    
    results = data["results"]
    
    # 1~6번은 모두 normal 이어야 함
    for i in range(6):
        assert results[i]["decision"] == "normal"
        assert results[i]["match_score"] > 50.0
        
    # 7번(영어)은 740이므로 오배열 이어야 함
    assert results[6]["decision"] == "suspected_misplacement"
    assert "740" in results[6]["reason"]
    
    print("Demo test scenario passed successfully!")
