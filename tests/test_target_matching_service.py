import subprocess
import sys

from worker.schemas.inference import OCRResultItem, TargetBook
from worker.services.target_matching_service import (
    call_number_similarity,
    find_target_book,
    is_confident_early_match,
    select_precision_ocr_orders,
    title_match_variants,
    title_similarity,
)

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


def test_exact_title_and_call_number_can_stop_target_search_early() -> None:
    response = find_target_book(
        TARGET,
        [
            ocr(1, "전혀 다른 책", "813.6 조92ㄱ", "다른 저자"),
            ocr(13, TARGET.title, TARGET.call_number, TARGET.author),
        ],
    )

    assert is_confident_early_match(response, latest_order=13)


def test_ambiguous_target_search_does_not_stop_early() -> None:
    response = find_target_book(
        TARGET,
        [
            ocr(12, TARGET.title, TARGET.call_number, TARGET.author),
            ocr(13, TARGET.title, TARGET.call_number, TARGET.author),
        ],
    )

    assert not is_confident_early_match(response, latest_order=13)


def test_title_variants_remove_author_and_bibliographic_boilerplate() -> None:
    assert title_match_variants("열외인종 잔혹사 : 주원규 장편소설", "주원규") == ["열외인종잔혹사"]
    assert title_match_variants("코케인 = Cocaine : 진연주 장편소설", "진연주") == ["코케인", "cocaine"]


def test_shared_author_and_novel_label_are_not_distinctive_title_evidence() -> None:
    assert title_similarity(
        "열외인종 잔혹사 : 주원규 장편소설",
        "주원규 장편소설 망루",
        "주원규",
        "주원규",
    ) < 35


def test_different_joo_won_gyu_titles_do_not_select_the_same_neighbor() -> None:
    shelf = [
        ocr(16, "주원규 장편소설 망루", "813.6 주67ㅁ", "주원규"),
        ocr(19, "열외인종 잔혹사 주원규 장편소설", "813.6 주67ㅇ", "주원규"),
        ocr(20, "천하무적 불량야구단 주원규 장편소설", "813.6 주67ㅊ", "주원규"),
    ]
    outcast = find_target_book(
        TargetBook(
            holding_id="outcast",
            title="열외인종 잔혹사 : 주원규 장편소설",
            author="주원규",
            call_number="813.6 주67ㅇ",
        ),
        shelf,
    )
    baseball = find_target_book(
        TargetBook(
            holding_id="baseball",
            title="천하무적 불량야구단 : 주원규 장편소설",
            author="주원규",
            call_number="813.6 주67ㅊ",
        ),
        shelf,
    )

    assert outcast.status == "found"
    assert outcast.best_detection is not None
    assert outcast.best_detection.detected_order == 19
    assert baseball.status == "found"
    assert baseball.best_detection is not None
    assert baseball.best_detection.detected_order == 20
    assert next(item for item in outcast.detections if item.detected_order == 16).score < 65


def test_generic_only_ocr_cannot_become_a_possible_match() -> None:
    response = find_target_book(
        TargetBook(
            holding_id="outcast",
            title="열외인종 잔혹사 : 주원규 장편소설",
            author="주원규",
            call_number="813.6 주67ㅇ",
        ),
        [ocr(16, "주원규 장편소설", "813.6 주67ㅇ", "주원규")],
    )

    assert response.status == "not_found"


def test_precision_ocr_selects_call_number_neighbors_only_after_not_found() -> None:
    target = TargetBook(
        holding_id="baseball",
        title="천하무적 불량야구단 : 주원규 장편소설",
        author="주원규",
        call_number="813.6 주67ㅊ",
    )
    failed_fast_ocr = [
        ocr(16, "주원규 장편소설 망루", "813.6 주67ㅁ", "주원규"),
        ocr(20, "I 제 U Unabl 구면", "813.6 주67츠", None),
        ocr(31, "커피 먹는 염소", "813.6 진77ㅋ", "진주현"),
    ]

    assert select_precision_ocr_orders(target, failed_fast_ocr) == [20, 16]

    successful_fast_ocr = [
        *failed_fast_ocr,
        ocr(21, "천하무적 불량야구단", "813.6 주67ㅊ", "주원규"),
    ]
    assert select_precision_ocr_orders(target, successful_fast_ocr) == []


def test_target_matching_does_not_load_database_matching_stack() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import worker.services.target_matching_service; assert 'worker.services.matching_service' not in sys.modules",
        ],
        check=True,
    )
