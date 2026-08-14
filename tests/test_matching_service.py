from unittest.mock import AsyncMock, MagicMock

from worker.schemas.inference import OCRResultItem
from worker.services.matching_service import (
    find_matches_for_ocr_from_prisma_catalog,
    normalize_catalog_text,
    split_call_number,
)


def test_call_number_parser_preserves_hangul_and_compatibility_jamo() -> None:
    assert split_call_number("813.6 조92ㅊ") == ("813.6", "조92ㅊ")


def test_catalog_normalization_matches_importer_rules() -> None:
    assert normalize_catalog_text(" ８１３.６   조92ㅊ ") == normalize_catalog_text("813.6 조92ㅊ")


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
