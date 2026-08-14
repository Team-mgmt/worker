from worker.schemas.inference import DetectionResult, EstimatedShelf, MatchCandidate
from worker.services.decision_diagnostics_service import apply_detection_diagnostics


def result(order: int, call_number: str, *, confirmed: bool = True) -> DetectionResult:
    candidate = MatchCandidate(
        book_id=f"book-{order}",
        holding_id=f"holding-{order}",
        title=f"책 {order}",
        author="저자",
        call_number=call_number,
        score=90.0,
        match_method="call_number",
    )
    return DetectionResult(
        detected_order=order,
        ocr_raw_text=f"책 {order} {call_number}",
        ocr_title=f"책 {order}",
        ocr_call_number=call_number,
        ocr_confidence=0.95,
        matched_holding_id=candidate.holding_id if confirmed else None,
        matched_book_id=candidate.book_id if confirmed else None,
        matched_book=candidate.title if confirmed else None,
        matched_call_number=candidate.call_number if confirmed else None,
        match_score=90.0,
        decision="normal",
        top_candidates=[candidate],
    )


def test_diagnostics_separate_identification_range_order_and_ocr() -> None:
    results = [
        result(1, "813.6 조92ㅊ"),
        result(2, "813.6 조92ㅎ"),
        result(3, "500.1 김12ㄱ"),
        result(4, "813.6 주64ㅋ"),
        result(5, "813.6 주67ㅅ"),
    ]

    apply_detection_diagnostics(
        results,
        EstimatedShelf(kdc_start=810.0, kdc_end=819.99, confidence=0.8),
    )

    assert results[0].diagnostics is not None
    assert results[0].diagnostics.identification.status == "confirmed"
    assert results[0].diagnostics.shelf_range.status == "in_range"
    assert results[0].diagnostics.shelf_order.status == "in_order"
    assert results[0].diagnostics.ocr_quality.status == "good"
    assert results[2].diagnostics is not None
    assert results[2].diagnostics.shelf_range.status == "out_of_range"
    assert results[2].diagnostics.shelf_order.status == "out_of_order"


def test_unconfirmed_partial_ocr_is_explained_without_changing_legacy_decision() -> None:
    item = result(1, "813.6 진64ㅋ", confirmed=False)
    item.ocr_title = None
    item.decision = "needs_review"

    apply_detection_diagnostics([item], None)

    assert item.decision == "needs_review"
    assert item.diagnostics is not None
    assert item.diagnostics.identification.status == "candidate"
    assert item.diagnostics.shelf_range.status == "unknown"
    assert item.diagnostics.shelf_order.status == "unknown"
    assert item.diagnostics.ocr_quality.status == "partial"
