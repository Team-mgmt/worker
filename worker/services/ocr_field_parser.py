from __future__ import annotations

import re


CALL_NUMBER_PATTERN = re.compile(
    r"(?<!\d)"
    r"(?P<class_no>\d{3}(?:[.,:]\d+)?)"
    r"(?!\d)"
    r"(?:\s+\d{1,2})?"
    r"\s+"
    r"(?P<book_code>[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z]+\d+[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9.-]*)"
    r"(?:\s+(?P<copy_code>[cCvV]\.?(?:\s*)\d+))?"
)
AUTHOR_ROLE_PATTERN = re.compile(
    r"(?P<author>[가-힣]{2,4})\s*(?:지음|글|저|장편\s*소설|소설집|연작\s*소설)"
)
SHELF_LABEL_PATTERN = re.compile(r"\b(?:노원정보|노원중앙|문학|어학)\b")


def extract_ocr_fields(raw_text: str) -> tuple[str | None, str | None, str | None]:
    text = " ".join(raw_text.split())
    call_matches = list(CALL_NUMBER_PATTERN.finditer(text))
    call_match = call_matches[-1] if call_matches else None

    call_number = None
    bibliographic_text = text
    if call_match:
        class_no = call_match.group("class_no").replace(",", ".").replace(":", ".")
        book_code = call_match.group("book_code")
        copy_code = call_match.group("copy_code")
        call_number = " ".join(part for part in (class_no, book_code, copy_code) if part)
        bibliographic_text = text[: call_match.start()]

    bibliographic_text = SHELF_LABEL_PATTERN.sub(" ", bibliographic_text)
    bibliographic_text = " ".join(bibliographic_text.split()).strip(" -|,:")

    author = None
    title = bibliographic_text or None
    author_matches = list(AUTHOR_ROLE_PATTERN.finditer(bibliographic_text))
    if author_matches:
        author_match = author_matches[-1]
        author = author_match.group("author")
        title_prefix = bibliographic_text[: author_match.start()].strip(" -|,:")
        if title_prefix:
            title = title_prefix

    return title, author, call_number
