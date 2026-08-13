from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from worker.schemas.inference import OCRResultItem, TargetBook, TargetBookSearchResponse, TargetDetection
from worker.services.matching_service import split_call_number


FOUND_SCORE = 82.0
POSSIBLE_SCORE = 65.0
MIN_FOUND_MARGIN = 10.0


def normalize_match_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", "", normalized)


def text_similarity(first: str | None, second: str | None) -> float:
    left = normalize_match_text(first)
    right = normalize_match_text(second)
    if not left or not right:
        return 0.0
    return float(max(fuzz.ratio(left, right), fuzz.partial_ratio(left, right)))


def call_number_similarity(first: str | None, second: str | None) -> float:
    first_class, first_code = split_call_number(first or "")
    second_class, second_code = split_call_number(second or "")
    if not first_class or not second_class:
        return 0.0
    class_score = 100.0 if first_class == second_class else float(fuzz.ratio(first_class, second_class))
    code_score = text_similarity(first_code, second_code)
    return (class_score * 0.55) + (code_score * 0.45)


def score_target_detection(target: TargetBook, ocr: OCRResultItem) -> TargetDetection:
    title_source = ocr.title or ocr.raw_text
    title_score = text_similarity(target.title, title_source)
    author_score = text_similarity(target.author, ocr.author or ocr.raw_text)
    call_score = call_number_similarity(target.call_number, ocr.call_number)

    if call_score > 0:
        total_score = (call_score * 0.5) + (title_score * 0.4) + (author_score * 0.1)
    else:
        total_score = (title_score * 0.8) + (author_score * 0.2)
    return TargetDetection(
        detected_order=ocr.detected_order,
        bbox=ocr.bbox,
        obb_polygon=ocr.obb_polygon,
        ocr_raw_text=ocr.raw_text,
        ocr_title=ocr.title,
        ocr_author=ocr.author,
        ocr_call_number=ocr.call_number,
        score=round(total_score, 1),
        title_score=round(title_score, 1),
        author_score=round(author_score, 1),
        call_number_score=round(call_score, 1),
    )


def find_target_book(target: TargetBook, ocr_results: list[OCRResultItem]) -> TargetBookSearchResponse:
    detections = sorted(
        (score_target_detection(target, ocr) for ocr in ocr_results),
        key=lambda item: item.score,
        reverse=True,
    )
    best = detections[0] if detections else None
    second_score = detections[1].score if len(detections) > 1 else None
    margin = round(best.score - second_score, 1) if best and second_score is not None else None

    status = "not_found"
    if best and best.score >= FOUND_SCORE and (margin is None or margin >= MIN_FOUND_MARGIN):
        status = "found"
    elif best and best.score >= POSSIBLE_SCORE:
        status = "possible"

    return TargetBookSearchResponse(
        status=status,
        target=target,
        best_detection=best if status != "not_found" else None,
        second_best_score=second_score,
        score_margin=margin,
        location_hint=f"왼쪽에서 {best.detected_order}번째 책" if best and status != "not_found" else None,
        detections=detections,
    )
