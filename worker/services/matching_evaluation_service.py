from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from worker.schemas.artifact_evaluation import MatchingMetrics
from worker.services.detection_evaluation_service import bbox_polygon, polygon_iou
from worker.services.matching_service import normalize_catalog_text, normalize_core_title, split_call_number


class _EvaluationPrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bbox: list[float] | None = None
    obb_polygon: list[list[float]] | None = None
    ocr_title: str | None = None
    ocr_author: str | None = None
    ocr_call_number: str | None = None
    matched_holding_id: str | int | None = None
    matched_book_id: str | int | None = None
    top_candidates: list[dict[str, Any]] = Field(default_factory=list)


class _EvaluationInference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_EvaluationPrediction] = Field(default_factory=list)


class _EvaluationArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inference: _EvaluationInference = Field(default_factory=_EvaluationInference)


def _prediction_polygon(item: Mapping[str, Any]) -> list[list[float]] | None:
    polygon = item.get("obb_polygon")
    if isinstance(polygon, list) and len(polygon) == 4:
        return polygon
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return bbox_polygon(bbox)
    return None


def _normalized_call_number(value: str | None) -> str:
    return "".join(normalize_catalog_text(value).split())


def _same_identifier(candidate: Mapping[str, Any], annotation: Mapping[str, Any]) -> bool:
    holding_id = annotation.get("holding_id")
    if holding_id:
        return str(candidate.get("holding_id") or "") == str(holding_id)
    book_id = annotation.get("book_id")
    if book_id:
        return str(candidate.get("book_id") or "") == str(book_id)

    expected_title = normalize_core_title(annotation.get("title"), annotation.get("author"))
    candidate_title = normalize_core_title(candidate.get("title"), candidate.get("author"))
    expected_call = _normalized_call_number(annotation.get("call_number"))
    candidate_call = _normalized_call_number(candidate.get("call_number"))
    if expected_title and expected_call:
        return candidate_title == expected_title and candidate_call == expected_call
    if expected_title:
        return candidate_title == expected_title
    return bool(expected_call and candidate_call == expected_call)


def _accuracy(correct: int, evaluated: int) -> float:
    return round(correct / evaluated, 6) if evaluated else 0.0


def calculate_matching_metrics(
    result: Mapping[str, Any],
    annotations: Sequence[Mapping[str, Any]],
    iou_threshold: float = 0.5,
) -> MatchingMetrics | None:
    """Evaluate OCR fields and catalog ranking after polygon-aligning GT spines."""

    try:
        artifact = _EvaluationArtifact.model_validate(result)
    except ValidationError:
        return None
    predictions = [item.model_dump(mode="python") for item in artifact.inference.results]

    matched_predictions: set[int] = set()
    counters = {
        "polygon_matched": 0,
        "title_evaluated": 0,
        "title_correct": 0,
        "author_evaluated": 0,
        "author_correct": 0,
        "call_evaluated": 0,
        "call_correct": 0,
        "kdc_evaluated": 0,
        "kdc_correct": 0,
        "book_code_evaluated": 0,
        "book_code_correct": 0,
        "db_evaluated": 0,
        "top1_correct": 0,
        "top3_correct": 0,
        "confirmed": 0,
        "wrong_confirmed": 0,
    }

    for annotation in annotations:
        polygon = annotation.get("polygon")
        if not isinstance(polygon, list) or len(polygon) != 4:
            continue
        best_index = -1
        best_iou = 0.0
        for index, prediction in enumerate(predictions):
            if index in matched_predictions or not isinstance(prediction, Mapping):
                continue
            prediction_polygon = _prediction_polygon(prediction)
            if prediction_polygon is None:
                continue
            iou = polygon_iou(prediction_polygon, polygon)
            if iou > best_iou:
                best_index = index
                best_iou = iou
        if best_index < 0 or best_iou < iou_threshold:
            continue

        matched_predictions.add(best_index)
        counters["polygon_matched"] += 1
        prediction = predictions[best_index]

        expected_title = normalize_core_title(annotation.get("title"), annotation.get("author"))
        if expected_title:
            counters["title_evaluated"] += 1
            predicted_title = normalize_core_title(prediction.get("ocr_title"), prediction.get("ocr_author"))
            counters["title_correct"] += int(predicted_title == expected_title)

        expected_author = normalize_catalog_text(annotation.get("author"))
        if expected_author:
            counters["author_evaluated"] += 1
            counters["author_correct"] += int(
                normalize_catalog_text(prediction.get("ocr_author")) == expected_author
            )

        expected_call = _normalized_call_number(annotation.get("call_number"))
        if expected_call:
            counters["call_evaluated"] += 1
            predicted_call = _normalized_call_number(prediction.get("ocr_call_number"))
            counters["call_correct"] += int(predicted_call == expected_call)
            expected_kdc, expected_book_code = split_call_number(annotation.get("call_number") or "")
            predicted_kdc, predicted_book_code = split_call_number(prediction.get("ocr_call_number") or "")
            if expected_kdc:
                counters["kdc_evaluated"] += 1
                counters["kdc_correct"] += int(predicted_kdc == expected_kdc)
            if expected_book_code:
                counters["book_code_evaluated"] += 1
                counters["book_code_correct"] += int(
                    normalize_catalog_text(predicted_book_code) == normalize_catalog_text(expected_book_code)
                )

        has_db_truth = bool(
            annotation.get("holding_id")
            or annotation.get("book_id")
            or annotation.get("title")
            or annotation.get("call_number")
        )
        if not has_db_truth:
            continue
        counters["db_evaluated"] += 1
        candidates = prediction.get("top_candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        top1_is_correct = bool(candidates and _same_identifier(candidates[0], annotation))
        counters["top1_correct"] += int(top1_is_correct)
        counters["top3_correct"] += int(
            any(_same_identifier(candidate, annotation) for candidate in candidates[:3] if isinstance(candidate, Mapping))
        )
        if prediction.get("matched_holding_id") or prediction.get("matched_book_id"):
            counters["confirmed"] += 1
            counters["wrong_confirmed"] += int(not top1_is_correct)

    if not counters["polygon_matched"]:
        return None
    return MatchingMetrics(
        iou_threshold=iou_threshold,
        polygon_matched_count=counters["polygon_matched"],
        title_evaluated_count=counters["title_evaluated"],
        title_correct=counters["title_correct"],
        title_normalized_accuracy=_accuracy(counters["title_correct"], counters["title_evaluated"]),
        author_evaluated_count=counters["author_evaluated"],
        author_correct=counters["author_correct"],
        author_normalized_accuracy=_accuracy(counters["author_correct"], counters["author_evaluated"]),
        call_number_evaluated_count=counters["call_evaluated"],
        call_number_correct=counters["call_correct"],
        call_number_exact_accuracy=_accuracy(counters["call_correct"], counters["call_evaluated"]),
        kdc_evaluated_count=counters["kdc_evaluated"],
        kdc_correct=counters["kdc_correct"],
        kdc_accuracy=_accuracy(counters["kdc_correct"], counters["kdc_evaluated"]),
        book_code_evaluated_count=counters["book_code_evaluated"],
        book_code_correct=counters["book_code_correct"],
        book_code_accuracy=_accuracy(counters["book_code_correct"], counters["book_code_evaluated"]),
        db_evaluated_count=counters["db_evaluated"],
        top1_correct=counters["top1_correct"],
        top1_accuracy=_accuracy(counters["top1_correct"], counters["db_evaluated"]),
        top3_correct=counters["top3_correct"],
        top3_accuracy=_accuracy(counters["top3_correct"], counters["db_evaluated"]),
        confirmed_count=counters["confirmed"],
        wrong_confirmation_count=counters["wrong_confirmed"],
        false_confirmation_rate=_accuracy(counters["wrong_confirmed"], counters["confirmed"]),
    )
