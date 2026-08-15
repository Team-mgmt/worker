from worker.api.artifact_evaluation import build_matching_diagnostics


def test_build_matching_diagnostics_exposes_normalization_and_shadow_strategies() -> None:
    result = {
        "inference": {
            "results": [
                {
                    "detected_order": 13,
                    "raw_text": "콩가루 수사단 주영하 장편소설 813.6 주64ㅋ",
                    "title": "콩가루 수사단 : 주영하 장편소설",
                    "author": "주영하",
                    "call_number": "813.6 주64ㅋ",
                }
            ]
        },
        "matching_comparison": {
            "spines": [
                {
                    "detected_order": 13,
                    "candidate_pool_size": 3,
                    "strategies": {"baseline": {"latency_ms": 0.1, "top_candidates": []}},
                }
            ]
        },
    }

    diagnostics = build_matching_diagnostics(result)

    assert diagnostics[0]["normalized_title"] == "콩가루 수사단"
    assert diagnostics[0]["kdc"] == "813.6"
    assert diagnostics[0]["book_code"] == "주64ㅋ"
    assert diagnostics[0]["comparison"]["candidate_pool_size"] == 3
