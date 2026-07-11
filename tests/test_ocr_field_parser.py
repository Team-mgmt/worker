from worker.services.ocr_field_parser import extract_ocr_fields
from worker.services.matching_service import split_call_number


def test_extracts_title_author_and_call_number() -> None:
    title, author, call_number = extract_ocr_fields(
        "민트의 세계 듀나 장편 소설 노원정보 문학 813.6 듀211ㅁ"
    )

    assert title == "민트의 세계"
    assert author == "듀나"
    assert call_number == "813.6 듀211ㅁ"


def test_ignores_title_year_and_normalizes_copy_number() -> None:
    title, author, call_number = extract_ocr_fields(
        "SF2021 판타지 오디세이 세 개의 달 노원정보 문학 813.6 듀211ㅅ C.2"
    )

    assert title == "SF2021 판타지 오디세이 세 개의 달"
    assert author is None
    assert call_number == "813.6 듀211ㅅ C.2"


def test_skips_stray_number_between_class_and_book_code() -> None:
    title, author, call_number = extract_ocr_fields(
        "여름과 루비 박연준 장편소설 노원중앙 문학 813.6 7 박64여 800"
    )

    assert title == "여름과 루비"
    assert author == "박연준"
    assert call_number == "813.6 박64여"


def test_matching_parser_preserves_korean_compatibility_jamo() -> None:
    assert split_call_number("813.6 듀211ㅁ") == ("813.6", "듀211ㅁ")
