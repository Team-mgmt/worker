import re
from typing import List, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from rapidfuzz import fuzz

from worker.db_models.catalog import Book, Holding
from worker.schemas.inference import MatchCandidate, OCRResultItem, DetectionResult, EstimatedShelf

def split_call_number(call_number: str) -> Tuple[str, str]:
    """Splits a call number into class_no and book_code by searching for patterns."""
    if not call_number:
        return "", ""
        
    # Search for \d{3} optionally followed by punctuation and digits
    match = re.search(r"(\d{3}[.,:]?\d*)", call_number)
    if not match:
        parts = call_number.split()
        return parts[0] if parts else "", parts[1] if len(parts) > 1 else ""
        
    class_no = match.group(1).replace(":", ".").replace(",", ".")
    
    # The book code is usually right after the class_no
    rest = call_number[match.end():].strip()
    book_code = ""
    if rest:
        # Match Korean char followed by numbers/chars
        bc_match = re.search(r"([가-힣][a-zA-Z0-9]*[가-힣]?)", rest)
        if bc_match:
            book_code = bc_match.group(1)
        else:
            book_code = rest.split()[0]
            
    return class_no, book_code

def compute_similarity(ocr_text: str, db_text: str) -> float:
    if not ocr_text or not db_text:
        return 0.0
    return fuzz.token_sort_ratio(ocr_text, db_text)

async def find_matches_for_ocr(
    session: AsyncSession, 
    library_code: str, 
    ocr_item: OCRResultItem
) -> List[MatchCandidate]:
    ocr_class_no, ocr_book_code = split_call_number(ocr_item.call_number or "")
    prefix = ocr_class_no[:2] if len(ocr_class_no) >= 2 else ocr_class_no[:1]
    
    # 1. DB 정보 검색 (Prefix 또는 저자 기호 첫 글자)
    from sqlalchemy import or_
    stmt = select(Holding, Book).join(Book).where(Holding.library_code == library_code)
    
    conditions = []
    if prefix:
        conditions.append(Holding.class_no_clean.like(f"{prefix}%"))
    if ocr_book_code:
        # 저자 기호 첫 글자 (예: '박')
        author_prefix = ocr_book_code[0]
        conditions.append(Holding.book_code.like(f"{author_prefix}%"))
        
    if conditions:
        stmt = stmt.where(or_(*conditions))
        
    result = await session.execute(stmt)
    rows = result.all()
    
    candidates = []
    
    # 2. RapidFuzz 개별 매칭
    for holding, book in rows:
        score_class = compute_similarity(ocr_class_no, holding.class_no_clean or holding.class_no)
        score_bcode = compute_similarity(ocr_book_code, holding.book_code)
        
        score_title = compute_similarity(ocr_item.title or ocr_item.raw_text, book.normalized_bookname or book.bookname)
        score_author = compute_similarity(ocr_item.author, book.normalized_authors or book.authors)
        
        # 가중합 (Weighting can be adjusted)
        # If OCR only has raw_text, title score is the main text score.
        total_score = (score_class * 0.4) + (score_bcode * 0.2) + (score_title * 0.3) + (score_author * 0.1)
        
        candidates.append(MatchCandidate(
            book_id=book.book_id,
            holding_id=holding.holding_id,
            title=book.bookname,
            author=book.authors or "",
            call_number=holding.call_number or "",
            score=total_score
        ))
        
    # 정렬 (점수 내림차순)
    candidates.sort(key=lambda x: x.score, reverse=True)
    
    # 동일 도서(book_id) 중복 제거 (가장 점수가 높거나 먼저 나온 holding_id만 유지)
    unique_candidates = []
    seen_book_ids = set()
    for c in candidates:
        if c.book_id not in seen_book_ids:
            unique_candidates.append(c)
            seen_book_ids.add(c.book_id)
            if len(unique_candidates) == 3:
                break
                
    return unique_candidates

def estimate_kdc_session(results: List[DetectionResult]) -> Optional[EstimatedShelf]:
    """세션 KDC 추정: 매칭 신뢰도가 높은 책들의 10단위 구간 비율 기반"""
    reliable_kdc = []
    reliable_full_classes = []
    for r in results:
        # 신뢰도 기준 (예: 60점 이상)
        if r.match_score and r.match_score >= 60.0 and r.top_candidates:
            c_num = r.top_candidates[0].call_number
            match = re.match(r"^([\d\.]+)", c_num)
            if match:
                try:
                    kdc_val = float(match.group(1))
                    reliable_kdc.append(kdc_val)
                    reliable_full_classes.append(match.group(1))
                except ValueError:
                    pass
                    
    if not reliable_kdc:
        return None
        
    bases = [(k // 10) * 10 for k in reliable_kdc]
    mode_base = max(set(bases), key=bases.count)
    dominant_count = bases.count(mode_base)
    ratio = dominant_count / len(bases)
    
    # 가장 많이 등장한 구체적 클래스 번호
    dominant_class = max(set(reliable_full_classes), key=reliable_full_classes.count)
    
    return EstimatedShelf(
        kdc_start=mode_base,
        kdc_end=mode_base + 9.99,
        dominant_class=dominant_class,
        confidence=ratio,
        basis=f"{dominant_count} of {len(bases)} high-confidence matched books"
    )

def evaluate_misplacement(result: DetectionResult, est_shelf: Optional[EstimatedShelf]) -> Tuple[str, Optional[str]]:
    """개별 도서 상태 및 사유 판정"""
    if result.match_score is None or result.match_score < 50.0:
        return "unmatched", None
        
    if result.score_margin is not None and result.score_margin < 10.0 and result.match_score < 80.0:
        return "needs_review", "점수 격차가 작아 검토 필요"
        
    if not result.top_candidates:
        return "unmatched", None
        
    c_num = result.top_candidates[0].call_number
    match = re.match(r"^([\d\.]+)", c_num)
    if match and est_shelf and est_shelf.kdc_start is not None:
        try:
            kdc_val = float(match.group(1))
            kdc_bin = (kdc_val // 10) * 10
            # 70% 비율 이상일 때만 확실하게 다른 서가로 간주
            if est_shelf.confidence is not None and est_shelf.confidence >= 0.7:
                if kdc_bin != est_shelf.kdc_start:
                    reason = f"주변 도서 대부분이 {est_shelf.dominant_class} 문맥이며 해당 도서는 {(kdc_val//10)*10:.0f} 분류임"
                    return "suspected_misplacement", reason
        except ValueError:
            pass
            
    return "normal", None
