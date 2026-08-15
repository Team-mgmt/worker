from worker.schemas.inference import OCRResultItem
from worker.services.matching_ablation_service import (
    MatchingAblationCase,
    cases_from_artifacts,
    evaluate_ablation_cases,
    score_candidate_rows,
)


def candidate(holding_id: str, title: str, call_number: str) -> dict:
    class_no, book_code = call_number.split(maxsplit=1)
    return {
        "holding_id": holding_id,
        "book_id": f"book-{holding_id}",
        "bookname": title,
        "normalized_bookname": title,
        "authors": "주영하",
        "normalized_authors": "주영하",
        "class_no": class_no,
        "class_no_clean": class_no,
        "book_code": book_code,
        "call_number": call_number,
    }


def test_score_candidate_rows_runs_all_ablation_strategies() -> None:
    ocr = OCRResultItem(
        detected_order=1,
        raw_text="콩가루 수사단 주영하 장편소설 813.6 주64ㅋ",
        title="콩가루 수사단 주영하 장편소설",
        author="주영하",
        call_number="813.6 주64ㅋ",
    )
    rows = [
        candidate("correct", "콩가루 수사단 : 주영하 장편소설", "813.6 주64ㅋ"),
        candidate("wrong", "시간의 계단 : 주영하 장편소설", "813.6 주64ㅅ"),
    ]

    for strategy in ("baseline", "preprocessed_fuzzy", "tfidf", "final"):
        ranked = score_candidate_rows(strategy, ocr, rows)
        assert ranked[0][0]["holding_id"] == "correct"
        assert ranked[0][1] >= ranked[1][1]


def test_evaluate_ablation_cases_reports_accuracy_latency_and_pool_misses() -> None:
    ocr = OCRResultItem(
        detected_order=1,
        title="콩가루 수사단",
        author="주영하",
        call_number="813.6 주64ㅋ",
    )
    correct_case = MatchingAblationCase(
        library_code="111058",
        run_id="run-1",
        ocr=ocr,
        holding_id="correct",
        book_id=None,
        title="콩가루 수사단 : 주영하 장편소설",
        author="주영하",
        call_number="813.6 주64ㅋ",
    )
    missing_case = MatchingAblationCase(
        library_code="111058",
        run_id="run-2",
        ocr=ocr,
        holding_id="missing",
        book_id=None,
        title="콩가루 수사단",
        author="주영하",
        call_number="813.6 주64ㅋ",
    )
    rows = [candidate("correct", "콩가루 수사단 : 주영하 장편소설", "813.6 주64ㅋ")]

    report = evaluate_ablation_cases([(correct_case, rows), (missing_case, rows)])

    assert set(report) == {"baseline", "preprocessed_fuzzy", "tfidf", "final"}
    assert report["final"]["evaluated_count"] == 2
    assert report["final"]["top1_accuracy"] == 0.5
    assert report["final"]["top3_accuracy"] == 0.5
    assert report["final"]["candidate_pool_miss_count"] == 1
    assert report["final"]["title_normalized_accuracy"] == 1.0
    assert report["final"]["call_number_exact_accuracy"] == 1.0
    assert report["final"]["reranking_latency_mean_ms"] >= 0
    assert report["final"]["reranking_latency_p95_ms"] >= 0


def test_cases_from_artifacts_supports_admin_result_field_names() -> None:
    result = {
        "run_id": "run-1",
        "library": {"code": "111058"},
        "inference": {
            "results": [
                {
                    "detected_order": 1,
                    "bbox": [0, 0, 100, 200],
                    "ocr_raw_text": "콩가루 수사단 주영하 813.6 주64ㅋ",
                    "ocr_title": "콩가루 수사단",
                    "ocr_author": "주영하",
                    "ocr_call_number": "813.6 주64ㅋ",
                }
            ]
        },
    }
    ground_truth = {
        "annotations": [
            {
                "polygon": [[0, 0], [100, 0], [100, 200], [0, 200]],
                "holding_id": "holding-1",
                "title": "콩가루 수사단 : 주영하 장편소설",
                "author": "주영하",
                "call_number": "813.6 주64ㅋ",
            }
        ]
    }

    cases = cases_from_artifacts(result, ground_truth)

    assert len(cases) == 1
    assert cases[0].holding_id == "holding-1"
    assert cases[0].ocr.title == "콩가루 수사단"
