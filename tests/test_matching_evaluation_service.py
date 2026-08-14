from worker.services.matching_evaluation_service import calculate_matching_metrics


def prediction(
    order: int,
    left: float,
    *,
    title: str,
    author: str,
    call_number: str,
    candidates: list[dict],
    matched_holding_id: str | None,
) -> dict:
    return {
        "detected_order": order,
        "bbox": [left, 0, left + 90, 200],
        "ocr_title": title,
        "ocr_author": author,
        "ocr_call_number": call_number,
        "top_candidates": candidates,
        "matched_holding_id": matched_holding_id,
    }


def annotation(left: float, *, holding_id: str, title: str, author: str, call_number: str) -> dict:
    return {
        "id": holding_id,
        "polygon": [[left, 0], [left + 90, 0], [left + 90, 200], [left, 200]],
        "holding_id": holding_id,
        "title": title,
        "author": author,
        "call_number": call_number,
    }


def test_matching_metrics_measure_ocr_ranking_and_false_confirmation() -> None:
    correct = {
        "holding_id": "holding-cocaine",
        "book_id": "book-cocaine",
        "title": "코케인 = Cocaine : 진연주 장편소설",
        "author": "진연주",
        "call_number": "813.6 진64ㅋ",
    }
    wrong = {
        "holding_id": "holding-other",
        "book_id": "book-other",
        "title": "다른 책",
        "author": "진연주",
        "call_number": "813.6 진64ㄷ",
    }
    result = {
        "inference": {
            "results": [
                prediction(
                    1,
                    0,
                    title="코케인",
                    author="진연주",
                    call_number="813.6 진64ㅋ",
                    candidates=[correct, wrong],
                    matched_holding_id="holding-cocaine",
                ),
                prediction(
                    2,
                    100,
                    title="시간의 계단",
                    author="주영하",
                    call_number="813.6 주64ㅅ",
                    candidates=[wrong, {**correct, "holding_id": "holding-time"}],
                    matched_holding_id="holding-other",
                ),
            ]
        }
    }
    annotations = [
        annotation(
            0,
            holding_id="holding-cocaine",
            title="코케인 = Cocaine : 진연주 장편소설",
            author="진연주",
            call_number="813.6 진64ㅋ",
        ),
        annotation(
            100,
            holding_id="holding-time",
            title="시간의 계단 : 주영하 장편소설",
            author="주영하",
            call_number="813.6 주64ㅅ",
        ),
    ]

    metrics = calculate_matching_metrics(result, annotations)

    assert metrics is not None
    assert metrics.polygon_matched_count == 2
    assert metrics.title_normalized_accuracy == 1.0
    assert metrics.call_number_exact_accuracy == 1.0
    assert metrics.top1_accuracy == 0.5
    assert metrics.top3_accuracy == 1.0
    assert metrics.confirmed_count == 2
    assert metrics.wrong_confirmation_count == 1
    assert metrics.false_confirmation_rate == 0.5


def test_matching_metrics_returns_none_without_polygon_matches() -> None:
    assert calculate_matching_metrics({"inference": {"results": []}}, []) is None
