from typing import List, Optional
from pydantic import BaseModel, Field

class OCRResultItem(BaseModel):
    raw_text: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    call_number: Optional[str] = None
    detected_order: int
    bbox: Optional[List[float]] = None
    ocr_confidence: Optional[float] = None

class ScanSessionRequest(BaseModel):
    library_code: str
    room_name: Optional[str] = None
    source_name: Optional[str] = None
    expected_shelf_start: Optional[float] = None
    expected_shelf_end: Optional[float] = None
    ocr_results: List[OCRResultItem]

class MatchCandidate(BaseModel):
    book_id: int
    holding_id: int
    title: str
    author: str
    call_number: str
    score: float

class DetectionResult(BaseModel):
    detected_order: int
    bbox: Optional[List[float]] = None
    matched_book: Optional[str] = None
    matched_call_number: Optional[str] = None
    match_score: Optional[float] = None
    decision: str # normal, suspected_misplacement, needs_review, unmatched
    reason: Optional[str] = None
    
    # Keeping extra debug fields optional
    ocr_call_number: Optional[str] = None
    ocr_title: Optional[str] = None
    matched_holding_id: Optional[int] = None
    matched_book_id: Optional[int] = None
    score_margin: Optional[float] = None
    top_candidates: List[MatchCandidate] = []

class EstimatedShelf(BaseModel):
    kdc_start: Optional[float] = None
    kdc_end: Optional[float] = None
    dominant_class: Optional[str] = None
    confidence: Optional[float] = None
    basis: Optional[str] = None

class MatchResponse(BaseModel):
    session_id: int
    library_code: str
    estimated_shelf: Optional[EstimatedShelf] = None
    results: List[DetectionResult]
