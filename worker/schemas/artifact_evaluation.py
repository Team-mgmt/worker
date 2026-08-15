from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GroundTruthAnnotation(BaseModel):
    id: str
    class_name: str = Field(default="book_spine", alias="class")
    polygon: list[list[float]]
    title: str | None = None
    author: str | None = None
    call_number: str | None = None
    holding_id: str | None = None
    book_id: str | None = None
    placement_status: Literal["normal", "misplaced"] | None = None

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, polygon: list[list[float]]) -> list[list[float]]:
        if len(polygon) != 4 or any(len(point) != 2 for point in polygon):
            raise ValueError("A book-spine polygon must contain exactly four [x, y] points.")
        return polygon


class GroundTruthSaveRequest(BaseModel):
    reviewer: str = "admin"
    annotations: list[GroundTruthAnnotation]


class DetectionMetrics(BaseModel):
    iou_threshold: float
    ground_truth_count: int
    prediction_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    ap50: float
    mean_matched_iou: float
    count_error: int


class DetectionMatch(BaseModel):
    status: Literal["matched", "false_positive", "missed"]
    ground_truth_index: int | None = None
    ground_truth_id: str | None = None
    prediction_index: int | None = None
    iou: float = 0.0
    confidence: float = 0.0
    ground_truth_polygon: list[list[float]] | None = None
    prediction_polygon: list[list[float]] | None = None


class DetectionStructureMetrics(BaseModel):
    ground_truth_count: int
    prediction_count: int
    correct_ground_truth_count: int
    split_ground_truth_count: int
    merged_ground_truth_count: int
    missed_ground_truth_count: int
    merged_prediction_count: int
    false_positive_prediction_count: int
    split_rate: float
    merge_rate: float
    minimum_small_polygon_coverage: float
    minimum_large_polygon_coverage: float


class PlacementMetrics(BaseModel):
    evaluated_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float
    recall: float
    f1: float


class MatchingMetrics(BaseModel):
    iou_threshold: float
    polygon_matched_count: int
    title_evaluated_count: int
    title_correct: int
    title_normalized_accuracy: float
    author_evaluated_count: int
    author_correct: int
    author_normalized_accuracy: float
    call_number_evaluated_count: int
    call_number_correct: int
    call_number_exact_accuracy: float
    kdc_evaluated_count: int
    kdc_correct: int
    kdc_accuracy: float
    book_code_evaluated_count: int
    book_code_correct: int
    book_code_accuracy: float
    db_evaluated_count: int
    top1_correct: int
    top1_accuracy: float
    top3_correct: int
    top3_accuracy: float
    confirmed_count: int
    wrong_confirmation_count: int
    false_confirmation_rate: float


class ArtifactRunSummary(BaseModel):
    run_id: str
    library_code: str
    created_at: datetime
    prefix: str
    has_ground_truth: bool


class ArtifactRunDetail(BaseModel):
    run_id: str
    prefix: str
    result: dict
    ground_truth: dict | None = None
    matching_diagnostics: list[dict] = Field(default_factory=list)
    image_width: int
    image_height: int
    original_url: str


class GroundTruthSaveResponse(BaseModel):
    key: str
    metrics: DetectionMetrics
    detection_matches: list[DetectionMatch]
    structure_metrics: DetectionStructureMetrics
    placement_metrics: PlacementMetrics | None = None
    matching_metrics: MatchingMetrics | None = None
    ground_truth: dict
