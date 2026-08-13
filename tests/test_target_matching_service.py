from worker.schemas.inference import OCRResultItem, TargetBook
from worker.services.target_matching_service import call_number_similarity, find_target_book


TARGET = TargetBook(
    holding_id="holding-1",
    title="환한 숨 : 조해진 소설집",
    author="조해진",
    call_number="813.6 조92ㅎ",
)


def ocr(order: int, title: str, call_number: str | None, author: str | None = None) -> OCRResultItem:
    return OCRResultItem(detected_order=order, title=title, author=author, call_number=call_number, raw_text=title)


def test_call_number_similarity_tolerates_one_ocr_character_error() -> None:
    assert call_number_similarity("813.6 조92ㅎ", "813.6 조92호") > 80


def test_target_book_is_found_at_its_detected_position() -> None:
    response = find_target_book(
        TARGET,
        [
            ocr(1, "완벽한 생애", "813.6 조92와", "조해진"),
            ocr(4, "환한 숨 조해진 소설", "813.6 조92호", "조해진"),
            ocr(7, "서초동 리그", "813.6 주67ㅅ", "주원규"),
        ],
    )

    assert response.status == "found"
    assert response.best_detection is not None
    assert response.best_detection.detected_order == 4
    assert response.location_hint == "왼쪽에서 4번째 책"


def test_similar_author_without_target_title_is_not_a_confirmed_find() -> None:
    response = find_target_book(
        TARGET,
        [ocr(1, "완벽한 생애", "813.6 조92와", "조해진"), ocr(2, "천사들의 도시", "813.6 조92ㅊ", "조해진")],
    )

    assert response.status != "found"
