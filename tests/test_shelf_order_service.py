from worker.schemas.inference import DetectionResult
from worker.services.shelf_order_service import (
    apply_shelf_order_decisions,
    call_number_sort_key,
    find_single_call_number_outlier,
)


def result(order: int, call_number: str | None, decision: str = "normal") -> DetectionResult:
    return DetectionResult(
        detected_order=order,
        ocr_call_number=call_number,
        decision=decision,
    )


def test_call_number_sort_key_orders_kdc_author_number_and_title_symbol() -> None:
    values = ["813.6 주67ㅅ", "813.6 조92ㅎ", "813.6 조92와", "813.7 가12ㄱ"]

    ordered = sorted(values, key=lambda value: call_number_sort_key(value))

    assert ordered == ["813.6 조92와", "813.6 조92ㅎ", "813.6 주67ㅅ", "813.7 가12ㄱ"]


def test_normal_shelf_has_no_order_outlier() -> None:
    results = [
        result(1, "813.6 조92와"),
        result(2, "813.6 조92ㅎ"),
        result(3, "813.6 주64ㅋ"),
        result(4, "813.6 주67ㅅ"),
    ]

    assert find_single_call_number_outlier(results) is None


def test_one_book_from_a_different_kdc_is_flagged() -> None:
    results = [
        result(1, "813.6 조92와", "needs_review"),
        result(2, "813.6 조92ㅎ", "needs_review"),
        result(3, "500.1 김12ㄱ", "needs_review"),
        result(4, "813.6 주64ㅋ", "needs_review"),
        result(5, "813.6 주67ㅅ", "needs_review"),
    ]

    apply_shelf_order_decisions(results)

    assert results[2].decision == "suspected_misplacement"
    assert "한 권을 제외하면" in (results[2].reason or "")
    assert all(item.decision == "needs_review" for item in results if item.detected_order != 3)


def test_one_book_moved_out_of_call_number_order_is_flagged() -> None:
    results = [
        result(1, "813.6 조92와"),
        result(2, "813.6 진67ㅁ"),
        result(3, "813.6 주64ㅋ"),
        result(4, "813.6 주67ㅅ"),
        result(5, "813.6 주68ㄴ"),
    ]

    assert find_single_call_number_outlier(results) == 2


def test_ambiguous_adjacent_swap_abstains() -> None:
    results = [
        result(1, "813.6 조92와"),
        result(2, "813.6 주67ㅅ"),
        result(3, "813.6 주64ㅋ"),
        result(4, "813.6 진67ㅁ"),
    ]

    assert find_single_call_number_outlier(results) is None


def test_unreadable_label_is_skipped_without_forcing_a_decision() -> None:
    results = [
        result(1, "813.6 조92와"),
        result(2, None, "needs_review"),
        result(3, "813.6 조92ㅎ"),
        result(4, "813.6 주64ㅋ"),
        result(5, "813.6 주67ㅅ"),
    ]

    apply_shelf_order_decisions(results)

    assert results[1].decision == "needs_review"
    assert all(item.decision != "suspected_misplacement" for item in results)
