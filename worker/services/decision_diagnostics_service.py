from __future__ import annotations

import re
from itertools import pairwise

from worker.schemas.inference import DecisionDiagnostic, DetectionDiagnostics, DetectionResult, EstimatedShelf
from worker.services.matching_service import has_ocr_evidence
from worker.services.shelf_order_service import call_number_sort_key, find_single_call_number_outlier


def _candidate_call_number(result: DetectionResult) -> str | None:
    return (
        result.matched_call_number
        or result.ocr_call_number
        or (result.top_candidates[0].call_number if result.top_candidates else None)
    )


def _identification(result: DetectionResult) -> DecisionDiagnostic:
    if result.matched_holding_id or result.matched_book_id:
        return DecisionDiagnostic(
            status="confirmed",
            label="도서 확정",
            reason="DB 후보가 현재 자동 확정 점수와 후보 차이 기준을 통과했습니다.",
        )
    if result.top_candidates:
        return DecisionDiagnostic(
            status="candidate",
            label="후보 있음",
            reason="DB 후보는 찾았지만 자동 확정 기준을 통과하지 못했습니다.",
        )
    return DecisionDiagnostic(
        status="unmatched",
        label="식별 실패",
        reason="선택한 도서관의 DB에서 대응되는 후보를 찾지 못했습니다.",
    )


def _shelf_range(result: DetectionResult, estimated_shelf: EstimatedShelf | None) -> DecisionDiagnostic:
    call_number = _candidate_call_number(result)
    match = re.match(r"^([\d.]+)", call_number or "")
    if (
        not match
        or estimated_shelf is None
        or estimated_shelf.kdc_start is None
        or estimated_shelf.confidence is None
        or estimated_shelf.confidence < 0.7
    ):
        return DecisionDiagnostic(
            status="unknown",
            label="범위 미확정",
            reason="청구기호 또는 신뢰할 수 있는 서가 대표 KDC 범위가 부족합니다.",
        )
    try:
        kdc_bin = (float(match.group(1)) // 10) * 10
    except ValueError:
        return DecisionDiagnostic(status="unknown", label="범위 미확정", reason="KDC 번호를 해석하지 못했습니다.")
    if kdc_bin != estimated_shelf.kdc_start:
        return DecisionDiagnostic(
            status="out_of_range",
            label="범위 이탈",
            reason=f"대표 서가 범위 {estimated_shelf.kdc_start:.0f}번대와 다른 KDC입니다.",
        )
    return DecisionDiagnostic(
        status="in_range",
        label="범위 정상",
        reason=f"대표 서가 범위 {estimated_shelf.kdc_start:.0f}번대 안에 있습니다.",
    )


def _ocr_quality(result: DetectionResult) -> DecisionDiagnostic:
    if not has_ocr_evidence(result):
        return DecisionDiagnostic(status="low", label="OCR 부족", reason="제목과 청구기호를 읽지 못했습니다.")
    if result.ocr_confidence is not None and result.ocr_confidence < 0.7:
        return DecisionDiagnostic(
            status="low",
            label="재촬영 권장",
            reason=f"OCR 평균 신뢰도가 {result.ocr_confidence:.2f}로 낮습니다.",
        )
    if result.ocr_title and result.ocr_call_number:
        return DecisionDiagnostic(status="good", label="OCR 양호", reason="제목과 청구기호를 모두 인식했습니다.")
    missing = "제목" if not result.ocr_title else "청구기호"
    return DecisionDiagnostic(
        status="partial",
        label="일부 인식",
        reason=f"{missing}를 인식하지 못해 다른 필드로 후보를 계산했습니다.",
    )


def apply_detection_diagnostics(
    results: list[DetectionResult],
    estimated_shelf: EstimatedShelf | None,
) -> None:
    """Attach independent identification, range, order, and OCR explanations."""

    ordered = sorted(results, key=lambda item: item.detected_order)
    parsed = [
        (item.detected_order, call_number_sort_key(_candidate_call_number(item)))
        for item in ordered
    ]
    parsed = [(order, key) for order, key in parsed if key is not None]
    is_sorted = len(parsed) >= 4 and all(
        previous[1] <= current[1] for previous, current in pairwise(parsed)
    )
    outlier_order = find_single_call_number_outlier(results)

    for result in results:
        if call_number_sort_key(_candidate_call_number(result)) is None or len(parsed) < 4:
            order_diagnostic = DecisionDiagnostic(
                status="unknown",
                label="순서 미확정",
                reason="세부 배열을 판단할 수 있는 청구기호가 부족합니다.",
            )
        elif outlier_order == result.detected_order:
            order_diagnostic = DecisionDiagnostic(
                status="out_of_order",
                label="순서 이탈",
                reason="이 책을 제외하면 좌우 청구기호 배열이 정상 순서로 복원됩니다.",
            )
        elif outlier_order is not None or is_sorted:
            order_diagnostic = DecisionDiagnostic(
                status="in_order",
                label="순서 정상",
                reason="인식 가능한 좌우 청구기호 순서와 일치합니다.",
            )
        else:
            order_diagnostic = DecisionDiagnostic(
                status="unknown",
                label="순서 검수",
                reason="여러 순서 역전 가능성이 있어 한 권을 자동 지목하지 않았습니다.",
            )

        result.diagnostics = DetectionDiagnostics(
            identification=_identification(result),
            shelf_range=_shelf_range(result, estimated_shelf),
            shelf_order=order_diagnostic,
            ocr_quality=_ocr_quality(result),
        )
