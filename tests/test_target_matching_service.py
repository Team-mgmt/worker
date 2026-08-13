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


def test_call_number_similarity_penalizes_a_different_title_symbol() -> None:
    matching = call_number_similarity("813.6 주64ㅋ", "813.6 주64크")
    different = call_number_similarity("813.6 주64ㅋ", "813.6 주64ㅇ")

    assert matching > 90
    assert different < 70


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


def test_ambiguous_result_returns_two_candidates_for_review() -> None:
    target = TargetBook(holding_id="holding-2", title="콩가루 수사단", author="주영하", call_number="813.6 주64ㅋ")
    response = find_target_book(
        target,
        [
            ocr(12, "주영선 장편소설 아웃", "813.6 주64ㅇ", "주영선"),
            ocr(13, "콩가루 수사단", "813.6 주64크", None),
            ocr(14, "기억의 문", "813.6 주67ㄱ", "주원규"),
        ],
    )

    assert response.status == "found"
    assert response.best_detection is not None
    assert response.best_detection.detected_order == 13
    assert response.best_detection.call_number_suffix_match is True


def test_possible_result_exposes_top_two_candidates() -> None:
    response = find_target_book(
        TARGET,
        [
            ocr(3, "환한 숨", "813.6 조92ㅎ"),
            ocr(4, "환한 숨", "813.6 조92ㅎ"),
        ],
    )

    assert response.status == "possible"
    assert [candidate.detected_order for candidate in response.candidate_detections] == [3, 4]
