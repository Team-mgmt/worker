from unittest.mock import AsyncMock, MagicMock

import pytest

from worker.schemas.inference import OCRResultItem
from worker.services.matching_service import (
    character_ngram_tfidf_cosines,
    find_matches_for_ocr_from_prisma_catalog,
    normalize_catalog_text,
    normalize_core_title,
    score_catalog_rows,
    split_call_number,
)


def test_call_number_parser_preserves_hangul_and_compatibility_jamo() -> None:
    assert split_call_number("813.6 조92ㅊ") == ("813.6", "조92ㅊ")


def test_catalog_normalization_matches_importer_rules() -> None:
    assert normalize_catalog_text(" ８１３.６   조92ㅊ ") == normalize_catalog_text("813.6 조92ㅊ")


def test_core_title_removes_author_and_nondistinctive_novel_suffixes() -> None:
    assert normalize_core_title("환한 숨 : 조해진 소설집", "조해진") == "환한 숨"
    assert normalize_core_title("시간의 계단 : 주영하 장편소설", "주영하") == "시간의 계단"


def test_core_title_keeps_principal_title_before_parallel_title() -> None:
    assert normalize_core_title(
        "코케인 = Cocaine : 진연주 장편소설",
        "진연주",
    ) == "코케인"


def test_character_ngram_tfidf_separates_other_books_by_the_same_author() -> None:
    scores = character_ngram_tfidf_cosines(
        "시간의 계단",
        ["시간의 계단", "콩가루 수사단", "완벽한 행운"],
    )

    assert scores[0] == pytest.approx(1.0)
    assert scores[0] - max(scores[1:]) > 0.8


async def test_exact_call_number_query_is_scored_without_fuzzy_catalog_scan() -> None:
    exact_result = MagicMock()
    exact_result.mappings.return_value.all.return_value = [
        {
            "holding_id": "holding-perfect-life",
            "class_no": "813.6",
            "class_no_clean": "813.6",
            "book_code": "조92와",
            "call_number": "813.6 조92와",
            "book_id": "book-perfect-life",
            "bookname": "완벽한 생애 : 조해진 소설",
            "normalized_bookname": "완벽한 생애 : 조해진 소설",
            "authors": "조해진",
            "normalized_authors": "조해진",
        }
    ]
    session = AsyncMock()
    session.execute.return_value = exact_result

    candidates = await find_matches_for_ocr_from_prisma_catalog(
        session,
        "111058",
        OCRResultItem(
            detected_order=2,
            raw_text="완벽한 생애 노원정보 문학 813.6 조92와",
            title="완벽한 생애",
            author="조해진",
            call_number="813.6 조92와",
        ),
    )

    assert session.execute.await_count == 1
    assert candidates[0].title == "완벽한 생애 : 조해진 소설"
    assert candidates[0].call_number == "813.6 조92와"
    assert candidates[0].score >= 85.0
    assert session.execute.await_args.args[1]["normalized_call_number"] == "813.6 조92와"


def test_core_title_reranking_separates_same_author_and_call_number_prefix() -> None:
    rows = [
        {
            "holding_id": "time-stairs",
            "class_no": "813.6",
            "class_no_clean": "813.6",
            "book_code": "주64ㅅ",
            "call_number": "813.6 주64ㅅ",
            "book_id": "book-time-stairs",
            "bookname": "시간의 계단 : 주영하 장편소설",
            "normalized_bookname": "시간의 계단 : 주영하 장편소설",
            "authors": "주영하",
            "normalized_authors": "주영하",
        },
        {
            "holding_id": "bean-powder-squad",
            "class_no": "813.6",
            "class_no_clean": "813.6",
            "book_code": "주64ㅋ",
            "call_number": "813.6 주64ㅋ",
            "book_id": "book-bean-powder-squad",
            "bookname": "콩가루 수사단 : 주영하 장편소설",
            "normalized_bookname": "콩가루 수사단 : 주영하 장편소설",
            "authors": "주영하",
            "normalized_authors": "주영하",
        },
    ]
    candidates = score_catalog_rows(
        rows,
        OCRResultItem(
            detected_order=12,
            title="시간의 계단",
            author="주영하",
            call_number="813.6 주64ㅅ",
        ),
        "813.6",
        "주64ㅅ",
    )

    assert candidates[0].title.startswith("시간의 계단")
    assert candidates[0].score - candidates[1].score >= 15.0


async def test_title_only_search_does_not_scan_arbitrary_catalog_rows() -> None:
    title_result = MagicMock()
    title_result.mappings.return_value = []
    session = AsyncMock()
    session.execute.return_value = title_result

    candidates = await find_matches_for_ocr_from_prisma_catalog(
        session,
        "111058",
        OCRResultItem(detected_order=30, title="코케인"),
    )

    assert candidates == []
    assert session.execute.await_count == 1
    statement = str(session.execute.await_args.args[0])
    assert 'b."normalizedBookname" ILIKE :title_pattern' in statement
    assert session.execute.await_args.args[1]["title_pattern"] == "%코케인%"
