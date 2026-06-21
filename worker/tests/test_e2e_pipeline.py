import os
import json
import asyncio
import cv2
import numpy as np

os.environ["USERPROFILE"] = r"C:\dev\paddle_models"
os.environ["HOMEDRIVE"] = "C:"
os.environ["HOMEPATH"] = r"\dev\paddle_models"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_mkldnn_bfloat16"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

import httpx
from worker.services.vision_service import vision_service

BBOXES_JSON = r"C:\dev\comp_lib\worker\worker\tests\bboxes.json"

COLORS = {
    "normal": (0, 255, 0), # Green
    "suspected_misplacement": (0, 0, 255), # Red
    "needs_review": (0, 255, 255), # Yellow
    "unmatched": (128, 128, 128) # Gray
}

def draw_and_save(img, scan_session, out_path):
    for result in scan_session["results"]:
        status = result["status"]
        color = COLORS.get(status, (255, 255, 255))
        
        # We stored original bbox in OCR result but the scan_session results doesn't have it directly.
        # We need to match it back, but let's just pass the bbox in the request so we can draw it.
        # Actually, let's extract bbox from our internal representation or just draw it before passing.
        pass

async def run_pipeline(mode="manual"):
    with open(BBOXES_JSON, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    outputs_dir = r"C:\dev\comp_lib\worker\outputs"
    os.makedirs(outputs_dir, exist_ok=True)
    
    for filename, manual_boxes in config.items():
        img_path = os.path.join(r"C:\dev\comp_lib\worker\worker\tests\test_images", filename)
        if not os.path.exists(img_path):
            print(f"Skipping {filename}: Not found")
            continue
            
        print(f"\nProcessing {filename} (Mode: {mode})...")
        
        # 1. Image Load & BBox
        img_array = np.fromfile(img_path, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if mode == "yolo":
            from worker.services.detection_service import detector_service
            try:
                # Use raw un-finetuned YOLOv8n to see if it runs
                detected_boxes = detector_service.detect_spines(img_path)
                boxes = [{"bbox": list(b)} for b in detected_boxes]
                print(f"YOLO detected {len(boxes)} spines.")
                if not boxes:
                    print("No boxes detected by YOLO. Skipping OCR.")
                    continue
            except Exception as e:
                print(f"YOLO detection failed: {e}")
                continue
        else:
            boxes = manual_boxes
            
        ocr_results_payload = []
        for i, box_info in enumerate(boxes):
            x, y, w, h = box_info["bbox"]
            
            # 2. Crop, Preprocess & OCR 
            try:
                extracted = vision_service.manual_crop_and_ocr(img_path, (x, y, w, h), preprocess=True)
                text = " ".join([res["text"] for res in extracted])
                confidence = sum([res["confidence"] for res in extracted]) / len(extracted) if extracted else 0.0
                print(f"BBox {i+1} OCR Result: '{text}' (conf: {confidence:.2f})")
            except Exception as e:
                print(f"OCR Error: {e}")
                text = ""
                confidence = 0.0

            # 3. Schema Conversion
            ocr_results_payload.append({
                "detected_order": i + 1,
                "raw_text": text,
                "title": None,
                "author": None,
                "call_number": text,
                "bbox": [x, y, x+w, y+h],
                "ocr_confidence": confidence
            })
            
        # 4. Matching Service
        # We estimate the current shelf context based on surrounding books
        request_data = {
            "library_code": "111058",
            "room_name": "노원중앙종합자료실",
            "source_name": filename,
            "estimated_shelf_start": 810.0,
            "estimated_shelf_end": 819.9,
            "shelf_confidence": 0.9,
            "ocr_results": ocr_results_payload
        }
        
        try:
            print("Calling matching service API...")
            async with httpx.AsyncClient() as client:
                response = await client.post("http://localhost:8000/inference/scan", json=request_data, timeout=30.0)
                if response.status_code != 200:
                    print(f"API Error {response.status_code}: {response.text}")
                    continue
                scan_session = response.json()
            
            # 5. Visualization
            for item in scan_session["results"]:
                idx = item["detected_order"] - 1
                x, y, x2, y2 = ocr_results_payload[idx]["bbox"]
                status = item["decision"] if "decision" in item else item.get("status", "unmatched")
                color = COLORS.get(status, (255, 255, 255))
                
                cv2.rectangle(img, (x, y), (x2, y2), color, 3)
                
                label = f"{item.get('ocr_call_number', '')} -> {status}"
                cv2.putText(img, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                
                print(f"Result {item['detected_order']}: Status={status}, Matched={item.get('matched_book_id')}, OCR='{item.get('ocr_call_number')}'")
                
            out_img = os.path.join(outputs_dir, f"result_{filename}")
            is_success, im_buf_arr = cv2.imencode('.png', img)
            if is_success:
                im_buf_arr.tofile(out_img)
                
            out_json = os.path.join(outputs_dir, f"result_{filename}.json")
            with open(out_json, 'w', encoding='utf-8') as f:
                json.dump(scan_session, f, ensure_ascii=False, indent=2)
                
            print(f"Saved visualization to {out_img}")
            print(f"Saved JSON to {out_json}")
            
        except Exception as e:
            print(f"Matching error: {e}")

async def main():
    print("--- Running Manual BBox Regression Test ---")
    await run_pipeline(mode="manual")
    
    print("\n--- Running YOLO E2E Test ---")
    await run_pipeline(mode="yolo")

if __name__ == '__main__':
    asyncio.run(main())
