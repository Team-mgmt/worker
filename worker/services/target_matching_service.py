from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from worker.schemas.inference import OCRResultItem, TargetBook, TargetBookSearchResponse, TargetDetection
from worker.services.matching_service import split_call_number

FOUND_SCORE = 82.0
POSSIBLE_SCORE = 65.0
MIN_FOUND_MARGIN = 10.0
EARLY_STOP_SCORE = 90.0
EARLY_STOP_FIELD_SCORE = 90.0
HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3
COMPATIBILITY_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
TITLE_BOILERPLATE = (
    "청소년장편소설",
    "장편소설",
    "연작소설",
    "청소년소설",
    "단편소설",
    "소설집",
    "수필집",
    "산문집",
    "동화집",
    "에세이",
    "시집",
    "소설",
    "대활자본",
    "큰글자책",
    "글그림",
    "글",
    "그림",
    "지음",
    "옮김",
)


def normalize_match_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", "", normalized)


def text_similarity(first: str | None, second: str | None) -> float:
    left = normalize_match_text(first)
    right = normalize_match_text(second)
    if not left or not right:
        return 0.0
    return float(max(fuzz.ratio(left, right), fuzz.partial_ratio(left, right)))


def _author_match_tokens(author: str | None) -> list[str]:
    compact = normalize_match_text(author)
    for phrase in TITLE_BOILERPLATE:
        compact = compact.replace(normalize_match_text(phrase), "")
    return [token for token in re.split(r"(?:외|등|역)", compact) if len(token) >= 2]


def title_match_variants(value: str | None, author: str | None = None) -> list[str]:
    """Return main-title variants without bibliographic boilerplate."""

    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    main_title = re.split(r"[:：]", normalized, maxsplit=1)[0]
    variants: list[str] = []
    for alias in re.split(r"[=＝]", main_title):
        compact = normalize_match_text(alias)
        for author_token in _author_match_tokens(author):
            compact = compact.replace(author_token, "")
        for phrase in TITLE_BOILERPLATE:
            compact = compact.replace(normalize_match_text(phrase), "")
        if compact and compact not in variants:
            variants.append(compact)
    return variants


def title_similarity(
    target_title: str | None,
    ocr_title: str | None,
    target_author: str | None = None,
    ocr_author: str | None = None,
) -> float:
    target_variants = title_match_variants(target_title, target_author)
    ocr_variants = title_match_variants(ocr_title, ocr_author or target_author)
    best = 0.0
    for target_variant in target_variants:
        for ocr_variant in ocr_variants:
            ratio = float(fuzz.ratio(target_variant, ocr_variant))
            length_ratio = min(len(target_variant), len(ocr_variant)) / max(len(target_variant), len(ocr_variant))
            partial = 0.0
            if min(len(target_variant), len(ocr_variant)) >= 3 and length_ratio >= 0.55:
                partial = float(fuzz.partial_ratio(target_variant, ocr_variant)) * 0.95
            best = max(best, ratio, partial)
    return best


def _initial_symbol(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        return ""
    first = normalized[0]
    codepoint = ord(first)
    if 0x1100 <= codepoint <= 0x1112:
        return COMPATIBILITY_INITIALS[codepoint - 0x1100]
    if HANGUL_BASE <= codepoint <= HANGUL_END:
        return COMPATIBILITY_INITIALS[(codepoint - HANGUL_BASE) // 588]
    return first


def _split_book_code(value: str) -> tuple[str, str]:
    compact = re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", "", value.casefold())
    match = re.match(r"^(.+?\d+)(.*)$", compact)
    if not match:
        return compact, ""
    return match.group(1), _initial_symbol(match.group(2))


def call_number_components(first: str | None, second: str | None) -> tuple[float, bool | None]:
    first_class, first_code = split_call_number(first or "")
    second_class, second_code = split_call_number(second or "")
    if not first_class or not second_class:
        return 0.0, None
    class_score = 100.0 if first_class == second_class else float(fuzz.ratio(first_class, second_class))
    first_stem, first_suffix = _split_book_code(first_code)
    second_stem, second_suffix = _split_book_code(second_code)
    stem_score = text_similarity(first_stem, second_stem)
    suffix_match: bool | None = None
    suffix_score = 0.0
    if first_suffix and second_suffix:
        suffix_match = first_suffix == second_suffix
        suffix_score = 100.0 if suffix_match else 0.0
    elif not first_suffix and not second_suffix:
        suffix_score = 50.0
    return (class_score * 0.25) + (stem_score * 0.4) + (suffix_score * 0.35), suffix_match


def call_number_similarity(first: str | None, second: str | None) -> float:
    score, _ = call_number_components(first, second)
    return score


def score_target_detection(target: TargetBook, ocr: OCRResultItem) -> TargetDetection:
    title_source = ocr.title or ocr.raw_text
    title_score = title_similarity(target.title, title_source, target.author, ocr.author)
    author_score = text_similarity(target.author, ocr.author or ocr.raw_text)
    call_score, suffix_match = call_number_components(target.call_number, ocr.call_number)

    if call_score > 0:
        total_score = (call_score * 0.45) + (title_score * 0.45) + (author_score * 0.1)
        if suffix_match is False:
            total_score -= 12.0
    else:
        total_score = (title_score * 0.8) + (author_score * 0.2)
    if title_score < 35.0:
        total_score = min(total_score, POSSIBLE_SCORE - 0.1)
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
        call_number_suffix_match=suffix_match,
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
        candidate_detections=detections[:2] if status == "possible" else ([best] if best and status == "found" else []),
        detections=detections,
    )


def is_confident_early_match(response: TargetBookSearchResponse, latest_order: int) -> bool:
    """Return true only when the latest OCR result is safe to accept immediately."""

    best = response.best_detection
    if response.status != "found" or best is None or best.detected_order != latest_order:
        return False
    if best.score < EARLY_STOP_SCORE or best.title_score < EARLY_STOP_FIELD_SCORE:
        return False
    if response.target.call_number and best.call_number_score < EARLY_STOP_FIELD_SCORE:
        return False
    return best.call_number_suffix_match is not False
