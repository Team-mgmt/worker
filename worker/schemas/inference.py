from typing import List, Optional, Union
from pydantic import BaseModel, Field

class OCRResultItem(BaseModel):
    raw_text: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    call_number: Optional[str] = None
    detected_order: int
    bbox: Optional[List[float]] = None
    crop_image_path: Optional[str] = None
    ocr_confidence: Optional[float] = None
    detection_confidence: Optional[float] = None
    obb_polygon: Optional[List[List[float]]] = None
    crop_method: Optional[str] = None
    crop_size: Optional[List[int]] = None
    ocr_variant: Optional[str] = None
    ocr_attempt_count: Optional[int] = None
    ocr_label_text: Optional[str] = None
    ocr_label_confidence: Optional[float] = None

class ScanSessionRequest(BaseModel):
    library_code: str
    room_name: Optional[str] = None
    source_name: Optional[str] = None
    expected_shelf_start: Optional[float] = None
    expected_shelf_end: Optional[float] = None
    ocr_results: List[OCRResultItem]

class MatchCandidate(BaseModel):
    book_id: Union[int, str]
    holding_id: Union[int, str]
    title: str
    author: str
    call_number: str
    score: float
    match_method: str

class DetectionResult(BaseModel):
    detected_order: int
    bbox: Optional[List[float]] = None
    crop_image_path: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_title: Optional[str] = None
    ocr_author: Optional[str] = None
    ocr_call_number: Optional[str] = None
    ocr_confidence: Optional[float] = None
    detection_confidence: Optional[float] = None
    obb_polygon: Optional[List[List[float]]] = None
    crop_method: Optional[str] = None
    crop_size: Optional[List[int]] = None
    ocr_variant: Optional[str] = None
    ocr_attempt_count: Optional[int] = None
    ocr_label_text: Optional[str] = None
    ocr_label_confidence: Optional[float] = None
    matched_book: Optional[str] = None
    matched_call_number: Optional[str] = None
    match_method: Optional[str] = None
    match_score: Optional[float] = None
    decision: str # normal, suspected_misplacement, needs_review, unmatched
    reason: Optional[str] = None
    matched_holding_id: Optional[Union[int, str]] = None
    matched_book_id: Optional[Union[int, str]] = None
    score_margin: Optional[float] = None
    top_candidates: List[MatchCandidate] = Field(default_factory=list)

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
    artifact_run_id: Optional[str] = None
    artifact_prefix: Optional[str] = None


class VideoFrameQuality(BaseModel):
    frame_index: int
    timestamp_seconds: float
    width: int
    height: int
    sharpness: float
    brightness: float
    contrast: float
    quality_score: float
    selected: bool = False


class VideoAnalysisResponse(BaseModel):
    video_run_id: str
    source_name: str
    duration_seconds: float
    sample_interval_seconds: float
    frame_candidates: List[VideoFrameQuality]
    selected_frame_data_url: str
    frame_selection_seconds: float
    total_seconds: float
    analysis: MatchResponse
    artifact_prefix: Optional[str] = None
