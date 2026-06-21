from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import os
import json

from worker.core.database import get_db
from worker.schemas.inference import ScanSessionRequest, MatchResponse, DetectionResult, MatchCandidate, OCRResultItem
from worker.db_models.inference import ScanSession, Detection
from worker.services.matching_service import find_matches_for_ocr, estimate_kdc_session, evaluate_misplacement

router = APIRouter(prefix="/inference", tags=["Inference"])

@router.post("/scan", response_model=MatchResponse)
async def process_scan_session(request: ScanSessionRequest, db: AsyncSession = Depends(get_db)):
    # 1. Create ScanSession
    session_db = ScanSession(
        library_code=request.library_code,
        room_name=request.room_name,
        expected_shelf_start=request.expected_shelf_start,
        expected_shelf_end=request.expected_shelf_end,
        source_type="API_MOCK",
        source_path=request.source_name
    )
    db.add(session_db)
    await db.flush() # get session_id
    
    detection_results: List[DetectionResult] = []
    
    # 2. Process each OCR item
    for ocr in request.ocr_results:
        candidates = await find_matches_for_ocr(db, request.library_code, ocr)
        
        top1_score = candidates[0].score if candidates else None
        top2_score = candidates[1].score if len(candidates) > 1 else None
        score_margin = (top1_score - top2_score) if top1_score is not None and top2_score is not None else None
        
        matched_holding_id = candidates[0].holding_id if candidates else None
        matched_book_id = candidates[0].book_id if candidates else None
        matched_book = candidates[0].title if candidates else None
        matched_call_number = candidates[0].call_number if candidates else None
        
        # Initial temp status, will be refined after KDC estimation
        res = DetectionResult(
            detected_order=ocr.detected_order,
            bbox=ocr.bbox,
            ocr_call_number=ocr.call_number,
            ocr_title=ocr.title,
            decision="unmatched", 
            matched_holding_id=matched_holding_id,
            matched_book_id=matched_book_id,
            matched_book=matched_book,
            matched_call_number=matched_call_number,
            match_score=top1_score,
            score_margin=score_margin,
            top_candidates=candidates
        )
        detection_results.append(res)
        
    # 3. KDC Session Estimation
    est_shelf = estimate_kdc_session(detection_results)
    
    # 4. Evaluate Misplacement
    for res in detection_results:
        decision, reason = evaluate_misplacement(res, est_shelf)
        res.decision = decision
        res.reason = reason
            
        # 5. Save Detections to DB
        det_db = Detection(
            scan_session_id=session_db.scan_session_id,
            detected_order=res.detected_order,
            ocr_raw_text=res.matched_book,
            ocr_call_number=res.ocr_call_number,
            ocr_confidence=ocr.ocr_confidence if hasattr(ocr, 'ocr_confidence') else None,
            matched_book_id=res.matched_book_id,
            matched_holding_id=res.matched_holding_id,
            match_score=res.match_score,
            score_margin=res.score_margin,
            status=res.decision,
            reason=res.reason
        )
        db.add(det_db)
        
    await db.commit()
    
    return MatchResponse(
        session_id=session_db.scan_session_id,
        library_code=request.library_code,
        estimated_shelf=est_shelf,
        results=detection_results
    )

@router.post("/upload_demo", response_model=MatchResponse)
async def upload_demo(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    filename = file.filename
    temp_path = os.path.join("outputs", filename)
    os.makedirs("outputs", exist_ok=True)
    with open(temp_path, "wb") as f:
        f.write(await file.read())
        
    bboxes_json = r"C:\dev\comp_lib\worker\worker\tests\bboxes.json"
    if not os.path.exists(bboxes_json):
        raise HTTPException(status_code=500, detail="bboxes.json not found")
        
    with open(bboxes_json, "r", encoding="utf-8") as f:
        bboxes_data = json.load(f)
        
    matched_key = None
    for k in bboxes_data.keys():
        if filename in k or k in filename:
            matched_key = k
            break
            
    if not matched_key:
        print(f"Filename {filename} didn't match. Defaulting to nowon_shelf_real_001.jpg")
        matched_key = "nowon_shelf_real_001.jpg"
        
    boxes = bboxes_data[matched_key]
    
    from worker.services.vision_service import vision_service
    ocr_results_payload = []
    
    # FOR DEMO: Use the original high-res image for OCR to avoid BBox misalignment 
    # caused by browser resizing or compression.
    pristine_img_path = os.path.join(r"C:\dev\comp_lib\worker\worker\tests\test_images", matched_key)
    
    for i, box_info in enumerate(boxes):
        x, y, w, h = box_info["bbox"]
        try:
            extracted = vision_service.manual_crop_and_ocr(pristine_img_path, (x, y, w, h), preprocess=True)
            text = " ".join([res["text"] for res in extracted])
            confidence = sum([res["confidence"] for res in extracted]) / len(extracted) if extracted else 0.0
        except Exception as e:
            print(f"OCR Error for box {i}: {e}")
            text = ""
            confidence = 0.0
            
        ocr_results_payload.append(OCRResultItem(
            detected_order=i+1,
            raw_text=text,
            title=box_info.get("expected_title"),
            call_number=text,
            bbox=[x, y, x+w, y+h],
            ocr_confidence=confidence
        ))
        
    req = ScanSessionRequest(
        library_code="111058",
        room_name="노원중앙종합자료실",
        source_name=filename,
        ocr_results=ocr_results_payload
    )
    
    return await process_scan_session(req, db)
