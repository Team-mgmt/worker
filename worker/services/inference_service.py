from __future__ import annotations

from typing import List

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from worker.db_models.inference import Detection, ScanSession
from worker.schemas.inference import DetectionResult, MatchCandidate, MatchResponse, OCRResultItem, ScanSessionRequest
from worker.services.matching_service import MIN_CONFIRMED_MATCH_SCORE, estimate_kdc_session, evaluate_misplacement, find_matches_for_ocr


async def process_scan_session_request(request: ScanSessionRequest, db: AsyncSession, persist: bool = True) -> MatchResponse:
    session_db = None
    if persist:
        session_db = ScanSession(
            library_code=request.library_code,
            room_name=request.room_name,
            expected_shelf_start=request.expected_shelf_start,
            expected_shelf_end=request.expected_shelf_end,
            source_type="upload" if request.source_name else "api",
            source_path=request.source_name,
        )
        db.add(session_db)
        await db.flush()

    detection_results: List[DetectionResult] = []
    source_items: dict[int, OCRResultItem] = {}

    for ocr in request.ocr_results:
        candidates = await find_matches_for_ocr(db, request.library_code, ocr)
        source_items[ocr.detected_order] = ocr

        top1_score = candidates[0].score if candidates else None
        top2_score = candidates[1].score if len(candidates) > 1 else None
        score_margin = (top1_score - top2_score) if top1_score is not None and top2_score is not None else None
        top_candidate = candidates[0] if candidates and top1_score is not None and top1_score >= MIN_CONFIRMED_MATCH_SCORE else None

        detection_results.append(
            DetectionResult(
                detected_order=ocr.detected_order,
                bbox=ocr.bbox,
                crop_image_path=ocr.crop_image_path,
                ocr_raw_text=ocr.raw_text,
                ocr_title=ocr.title,
                ocr_author=ocr.author,
                ocr_call_number=ocr.call_number,
                ocr_confidence=ocr.ocr_confidence,
                matched_holding_id=top_candidate.holding_id if top_candidate else None,
                matched_book_id=top_candidate.book_id if top_candidate else None,
                matched_book=top_candidate.title if top_candidate else None,
                matched_call_number=top_candidate.call_number if top_candidate else None,
                match_method=top_candidate.match_method if top_candidate else None,
                match_score=top1_score,
                score_margin=score_margin,
                decision="unmatched",
                top_candidates=candidates,
            )
        )

    estimated_shelf = estimate_kdc_session(detection_results)
    if estimated_shelf and session_db is not None:
        session_db.estimated_shelf_start = estimated_shelf.kdc_start
        session_db.estimated_shelf_end = estimated_shelf.kdc_end
        session_db.shelf_confidence = estimated_shelf.confidence

    candidate_adapter = TypeAdapter(List[MatchCandidate])
    for result in detection_results:
        decision, reason = evaluate_misplacement(result, estimated_shelf)
        result.decision = decision
        result.reason = reason
        ocr = source_items[result.detected_order]
        matched_book_id_for_db = result.matched_book_id if isinstance(result.matched_book_id, int) else None
        matched_holding_id_for_db = result.matched_holding_id if isinstance(result.matched_holding_id, int) else None

        if session_db is not None:
            db.add(
                Detection(
                    scan_session_id=session_db.scan_session_id,
                    detected_order=result.detected_order,
                    bbox=ocr.bbox,
                    crop_image_path=ocr.crop_image_path,
                    ocr_raw_text=ocr.raw_text,
                    ocr_title=ocr.title,
                    ocr_author=ocr.author,
                    ocr_call_number=ocr.call_number,
                    ocr_confidence=ocr.ocr_confidence,
                    matched_book_id=matched_book_id_for_db,
                    matched_holding_id=matched_holding_id_for_db,
                    match_method=result.match_method,
                    match_score=result.match_score,
                    score_margin=result.score_margin,
                    top_candidates=candidate_adapter.dump_python(result.top_candidates, mode="json"),
                    status=result.decision,
                    reason=result.reason,
                )
            )

    if session_db is not None:
        await db.commit()

    return MatchResponse(
        session_id=session_db.scan_session_id if session_db is not None else 0,
        library_code=request.library_code,
        estimated_shelf=estimated_shelf,
        results=detection_results,
    )
