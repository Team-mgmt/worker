from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class GroundTruthAnnotation(BaseModel):
    id: str
    class_name: str = Field(default="book_spine", alias="class")
    polygon: list[list[float]]
    title: str | None = None
    author: str | None = None
    call_number: str | None = None

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
    image_width: int
    image_height: int
    original_url: str


class GroundTruthSaveResponse(BaseModel):
    key: str
    metrics: DetectionMetrics
    ground_truth: dict
