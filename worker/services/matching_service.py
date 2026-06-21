import re
from typing import List, Optional, Tuple

from rapidfuzz import fuzz
from sqlalchemy import or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from worker.db_models.catalog import Book, Holding
from worker.schemas.inference import DetectionResult, EstimatedShelf, MatchCandidate, OCRResultItem


MIN_CONFIRMED_MATCH_SCORE = 75.0


def split_call_number(call_number: str) -> Tuple[str, str]:
    """Split a Korean library call number into KDC class number and book code."""
    if not call_number:
        return "", ""

    match = re.search(r"(\d{3}(?:[.,:]\d+)?)", call_number)
    if not match:
        parts = call_number.split()
        return parts[0] if parts else "", parts[1] if len(parts) > 1 else ""

    class_no = match.group(1).replace(":", ".").replace(",", ".")
    rest = call_number[match.end() :].strip()
    if not rest:
        return class_no, ""

    hangul_book_code_match = re.search(r"([가-힣A-Za-z0-9.-]+)", rest)
    if hangul_book_code_match:
        return class_no, hangul_book_code_match.group(1)

    book_code_match = re.search(r"([가-힣A-Za-z0-9.-]+)", rest)
    book_code = book_code_match.group(1) if book_code_match else rest.split()[0]
    return class_no, book_code


def has_reliable_book_code(book_code: str) -> bool:
    """Author symbols usually include digits, e.g. bak94gu or han12j."""
    return bool(book_code and re.search(r"\d", book_code))


def has_ocr_evidence(result: DetectionResult) -> bool:
    return any(
        bool(value and value.strip())
        for value in (result.ocr_call_number, result.ocr_title, result.ocr_author, result.ocr_raw_text)
    )


def compute_similarity(ocr_text: str | None, db_text: str | None) -> float:
    if not ocr_text or not db_text:
        return 0.0
    return float(fuzz.token_sort_ratio(ocr_text, db_text))


def compute_total_score(
    score_class: float,
    score_bcode: float,
    score_title: float,
    score_author: float,
    has_class_no: bool,
    has_reliable_bcode: bool,
) -> tuple[float, str]:
    bibliographic_score = (score_title * 0.8) + (score_author * 0.2)
    call_number_score = (score_class * 0.55) + (score_bcode * 0.45)

    if has_class_no and has_reliable_bcode:
        return (call_number_score * 0.65) + (bibliographic_score * 0.35), "call_number"

    if has_class_no:
        return (bibliographic_score * 0.9) + (score_class * 0.1), "bibliographic_fuzzy"

    return bibliographic_score, "bibliographic_fuzzy"


def unique_top_candidates(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
    unique_candidates: list[MatchCandidate] = []
    seen_candidate_keys: set[tuple[str, str]] = set()
    for candidate in candidates:
        candidate_key = (candidate.title, candidate.call_number)
        if candidate_key in seen_candidate_keys:
            continue
        unique_candidates.append(candidate)
        seen_candidate_keys.add(candidate_key)
        if len(unique_candidates) == 3:
            break
    return unique_candidates


async def find_matches_for_ocr(
    session: AsyncSession,
    library_code: str,
    ocr_item: OCRResultItem,
) -> List[MatchCandidate]:
    prisma_candidates = await find_matches_for_ocr_from_prisma_catalog(session, library_code, ocr_item)
    return prisma_candidates

    ocr_class_no, ocr_book_code = split_call_number(ocr_item.call_number or "")
    prefix = ocr_class_no[:2] if len(ocr_class_no) >= 2 else ocr_class_no[:1]

    stmt = select(Holding, Book).join(Book).where(Holding.library_code == library_code)
    conditions = []
    if prefix:
        conditions.append(Holding.class_no_clean.like(f"{prefix}%"))
    if ocr_book_code and has_reliable_book_code(ocr_book_code):
        conditions.append(Holding.book_code.like(f"{ocr_book_code[0]}%"))
    if conditions:
        stmt = stmt.where(or_(*conditions))

    result = await session.execute(stmt)
    rows = result.all()

    candidates: List[MatchCandidate] = []
    for holding, book in rows:
        score_class = compute_similarity(ocr_class_no, holding.class_no_clean or holding.class_no)
        score_bcode = compute_similarity(ocr_book_code, holding.book_code)
        score_title = compute_similarity(ocr_item.title or ocr_item.raw_text, book.normalized_bookname or book.bookname)
        score_author = compute_similarity(ocr_item.author, book.normalized_authors or book.authors)
        total_score, match_method = compute_total_score(
            score_class,
            score_bcode,
            score_title,
            score_author,
            bool(ocr_class_no),
            has_reliable_book_code(ocr_book_code),
        )

        candidates.append(
            MatchCandidate(
                book_id=book.book_id,
                holding_id=holding.holding_id,
                title=book.bookname,
                author=book.authors or "",
                call_number=holding.call_number or "",
                score=total_score,
                match_method=match_method,
            )
        )

    candidates.sort(key=lambda x: x.score, reverse=True)
    return unique_top_candidates(candidates)


async def find_matches_for_ocr_from_prisma_catalog(
    session: AsyncSession,
    library_code: str,
    ocr_item: OCRResultItem,
) -> List[MatchCandidate]:
    """Match OCR text against the Prisma PostgreSQL catalog tables used by shelfalign-web."""
    ocr_class_no, ocr_book_code = split_call_number(ocr_item.call_number or "")
    prefix = ocr_class_no[:2] if len(ocr_class_no) >= 2 else ocr_class_no[:1]

    where_parts = ['h."libraryCode" = :library_code']
    params: dict[str, str] = {"library_code": library_code}
    if prefix:
        where_parts.append('h."classNoClean" LIKE :class_prefix')
        params["class_prefix"] = f"{prefix}%"
    if ocr_book_code and has_reliable_book_code(ocr_book_code):
        where_parts.append('h."bookCode" LIKE :book_code_prefix')
        params["book_code_prefix"] = f"{ocr_book_code[0]}%"

    stmt = text(
        f"""
        SELECT
          h.id AS holding_id,
          h."classNo" AS class_no,
          h."classNoClean" AS class_no_clean,
          h."bookCode" AS book_code,
          h."callNumber" AS call_number,
          b.id AS book_id,
          b.bookname AS bookname,
          b."normalizedBookname" AS normalized_bookname,
          b.authors AS authors,
          b."normalizedAuthors" AS normalized_authors
        FROM "LibraryHolding" h
        JOIN "LibraryBook" b ON b.id = h."bookId"
        WHERE {" AND ".join(where_parts)}
        LIMIT 1500
        """
    )

    try:
        result = await session.execute(stmt, params)
    except Exception:
        await session.rollback()
        return []

    candidates: List[MatchCandidate] = []
    for row in result.mappings():
        score_class = compute_similarity(ocr_class_no, row["class_no_clean"] or row["class_no"])
        score_bcode = compute_similarity(ocr_book_code, row["book_code"])
        score_title = compute_similarity(ocr_item.title or ocr_item.raw_text, row["normalized_bookname"] or row["bookname"])
        score_author = compute_similarity(ocr_item.author, row["normalized_authors"] or row["authors"])
        total_score, match_method = compute_total_score(
            score_class,
            score_bcode,
            score_title,
            score_author,
            bool(ocr_class_no),
            has_reliable_book_code(ocr_book_code),
        )

        candidates.append(
            MatchCandidate(
                book_id=str(row["book_id"]),
                holding_id=str(row["holding_id"]),
                title=row["bookname"],
                author=row["authors"] or "",
                call_number=row["call_number"] or "",
                score=total_score,
                match_method=match_method,
            )
        )

    candidates.sort(key=lambda x: x.score, reverse=True)
    return unique_top_candidates(candidates)


def estimate_kdc_session(results: List[DetectionResult]) -> Optional[EstimatedShelf]:
    """Estimate the dominant KDC range from high-confidence matched books."""
    reliable_kdc: list[float] = []
    reliable_full_classes: list[str] = []
    for result in results:
        if result.match_score and result.match_score >= MIN_CONFIRMED_MATCH_SCORE and result.top_candidates:
            call_number = result.top_candidates[0].call_number
            match = re.match(r"^([\d.]+)", call_number)
            if not match:
                continue
            try:
                reliable_kdc.append(float(match.group(1)))
                reliable_full_classes.append(match.group(1))
            except ValueError:
                continue

    if not reliable_kdc:
        return None

    bases = [(kdc // 10) * 10 for kdc in reliable_kdc]
    mode_base = max(set(bases), key=bases.count)
    dominant_count = bases.count(mode_base)
    confidence = dominant_count / len(bases)
    dominant_class = max(set(reliable_full_classes), key=reliable_full_classes.count)

    return EstimatedShelf(
        kdc_start=mode_base,
        kdc_end=mode_base + 9.99,
        dominant_class=dominant_class,
        confidence=confidence,
        basis=f"{dominant_count} of {len(bases)} high-confidence matched books",
    )


def evaluate_misplacement(result: DetectionResult, est_shelf: Optional[EstimatedShelf]) -> Tuple[str, Optional[str]]:
    """Classify a detected book using match confidence and shelf context."""
    if not result.top_candidates:
        if has_ocr_evidence(result):
            return "needs_review", "OCR \ud14d\uc2a4\ud2b8\ub294 \uc778\uc2dd\ud588\uc9c0\ub9cc DB \ud6c4\ubcf4\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uc801\uc7ac \ubc94\uc704 \ub610\ub294 \uccad\uad6c\uae30\ud638 \uc778\uc2dd\uc744 \ud655\uc778\ud574\uc57c \ud569\ub2c8\ub2e4."
        return "unmatched", None

    if result.match_score is None or result.match_score < 50.0:
        if has_ocr_evidence(result):
            return "needs_review", "OCR \ud14d\uc2a4\ud2b8\ub294 \uc778\uc2dd\ud588\uc9c0\ub9cc DB \ub9e4\uce6d \uc810\uc218\uac00 \ub0ae\uc544 \uc218\ub3d9 \uac80\uc218\uac00 \ud544\uc694\ud569\ub2c8\ub2e4."
        return "unmatched", None

    if result.match_score < MIN_CONFIRMED_MATCH_SCORE:
        return "needs_review", "\ub9e4\uce6d \uc810\uc218\uac00 \ub0ae\uc544 \ud655\uc815 \ub3c4\uc11c\ub85c \ud310\uc815\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4."

    if result.score_margin is not None and result.score_margin < 10.0 and result.match_score < 85.0:
        return "needs_review", "\uc0c1\uc704 \ud6c4\ubcf4 \uac04 \uc810\uc218 \ucc28\uc774\uac00 \uc791\uc544 \uac80\uc218\uac00 \ud544\uc694\ud569\ub2c8\ub2e4."

    call_number = result.top_candidates[0].call_number
    match = re.match(r"^([\d.]+)", call_number)
    if match and est_shelf and est_shelf.kdc_start is not None:
        try:
            kdc_val = float(match.group(1))
        except ValueError:
            return "normal", None

        kdc_bin = (kdc_val // 10) * 10
        if est_shelf.confidence is not None and est_shelf.confidence >= 0.7 and kdc_bin != est_shelf.kdc_start:
            reason = f"\uc8fc\ubcc0 \uc11c\uac00\uc758 \uc8fc \ubd84\ub958\ub294 {est_shelf.dominant_class}\uc778\ub370, \uc774 \ucc45\uc740 KDC {kdc_bin:.0f} \uacc4\uc5f4\uc785\ub2c8\ub2e4."
            return "suspected_misplacement", reason

    return "normal", None
