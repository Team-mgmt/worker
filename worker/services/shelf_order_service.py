from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from worker.schemas.inference import DetectionResult
from worker.services.matching_service import split_call_number


_COPY_SUFFIX_PATTERN = re.compile(r"(?:\s|^)(?:c\.?\s*\d+|v\.?\s*\d+|권\s*\d*)\b.*$", re.IGNORECASE)
_NATURAL_TOKEN_PATTERN = re.compile(r"\d+|\D+")


@dataclass(frozen=True, order=True)
class CallNumberSortKey:
    """Comparable representation of the KDC class and author/book symbol."""

    class_number: Decimal
    book_code_tokens: tuple[tuple[int, int | str], ...]


def _natural_tokens(value: str) -> tuple[tuple[int, int | str], ...]:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    compact = re.sub(r"[\s._:/-]+", "", normalized)
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token)
        for token in _NATURAL_TOKEN_PATTERN.findall(compact)
    )


def call_number_sort_key(call_number: str | None) -> CallNumberSortKey | None:
    """Parse a call number into a stable ascending shelf-order key.

    Copy/volume suffixes are deliberately ignored because copies of the same title
    occupy the same logical shelf position. Unparseable or class-only labels are
    excluded from automatic placement decisions.
    """

    class_no, book_code = split_call_number(call_number or "")
    if not class_no or not book_code:
        return None
    try:
        class_number = Decimal(class_no)
    except InvalidOperation:
        return None

    book_code = _COPY_SUFFIX_PATTERN.sub("", book_code).strip()
    tokens = _natural_tokens(book_code)
    if not tokens:
        return None
    return CallNumberSortKey(class_number=class_number, book_code_tokens=tokens)


def _is_non_decreasing(keys: list[CallNumberSortKey]) -> bool:
    return all(previous <= current for previous, current in zip(keys, keys[1:], strict=False))


def find_single_call_number_outlier(results: list[DetectionResult]) -> int | None:
    """Return the detected order of one unambiguous misplaced spine.

    Missing/unparseable labels are skipped. A result is flagged only when the
    remaining sequence becomes sorted after removing exactly one item. If two
    removals could both explain the inversion (for example an adjacent swap), the
    function abstains instead of accusing an arbitrary book.
    """

    ordered_results = sorted(results, key=lambda result: result.detected_order)
    parsed: list[tuple[int, CallNumberSortKey]] = []
    for result in ordered_results:
        candidate_call_number = (
            result.matched_call_number
            or result.ocr_call_number
            or (result.top_candidates[0].call_number if result.top_candidates else None)
        )
        key = call_number_sort_key(candidate_call_number)
        if key is not None:
            parsed.append((result.detected_order, key))

    if len(parsed) < 4:
        return None
    keys = [key for _, key in parsed]
    if _is_non_decreasing(keys):
        return None

    removable_indices = [
        index
        for index in range(len(keys))
        if _is_non_decreasing(keys[:index] + keys[index + 1 :])
    ]
    if len(removable_indices) != 1:
        return None
    return parsed[removable_indices[0]][0]


def apply_shelf_order_decisions(results: list[DetectionResult]) -> None:
    """Promote an unambiguous call-number order outlier to misplacement."""

    outlier_order = find_single_call_number_outlier(results)
    if outlier_order is None:
        return
    for result in results:
        if result.detected_order == outlier_order:
            result.decision = "suspected_misplacement"
            result.reason = "좌우 청구기호 순서에서 이 책 한 권을 제외하면 나머지 배열이 정상 순서로 복원됩니다."
            return
