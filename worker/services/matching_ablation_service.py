from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rapidfuzz import fuzz

from worker.schemas.inference import OCRResultItem
from worker.services.detection_evaluation_service import bbox_polygon, polygon_iou
from worker.services.matching_service import (
    character_ngram_tfidf_cosines,
    compute_similarity,
    compute_total_score,
    has_reliable_book_code,
    normalize_catalog_text,
    normalize_core_title,
    split_call_number,
)

AblationStrategy = Literal["baseline", "preprocessed_fuzzy", "tfidf", "final"]
STRATEGIES: tuple[AblationStrategy, ...] = (
    "baseline",
    "preprocessed_fuzzy",
    "tfidf",
    "final",
)


class ShadowCandidate(BaseModel):
    rank: int
    holding_id: str
    book_id: str
    title: str
    author: str
    call_number: str
    score: float


class ShadowStrategyResult(BaseModel):
    latency_ms: float
    top_candidates: list[ShadowCandidate] = Field(default_factory=list)


class ShadowSpineComparison(BaseModel):
    detected_order: int
    candidate_pool_size: int
    strategies: dict[AblationStrategy, ShadowStrategyResult]


class MatchingShadowComparison(BaseModel):
    schema_version: str = "1.0"
    total_latency_ms: float
    spines: list[ShadowSpineComparison] = Field(default_factory=list)


@dataclass(frozen=True)
class MatchingAblationCase:
    library_code: str
    run_id: str
    ocr: OCRResultItem
    holding_id: str | None
    book_id: str | None
    title: str | None
    author: str | None
    call_number: str | None


class _ArtifactLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str


class _ArtifactPrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    detected_order: int
    bbox: list[float] | None = None
    obb_polygon: list[list[float]] | None = None
    raw_text: str | None = None
    title: str | None = None
    author: str | None = None
    call_number: str | None = None
    ocr_raw_text: str | None = None
    ocr_title: str | None = None
    ocr_author: str | None = None
    ocr_call_number: str | None = None

    def as_ocr_result(self) -> OCRResultItem:
        return OCRResultItem(
            detected_order=self.detected_order,
            bbox=self.bbox,
            obb_polygon=self.obb_polygon,
            raw_text=self.ocr_raw_text or self.raw_text,
            title=self.ocr_title or self.title,
            author=self.ocr_author or self.author,
            call_number=self.ocr_call_number or self.call_number,
        )


class _ArtifactInference(BaseModel):
    model_config = ConfigDict(extra="ignore")
    results: list[_ArtifactPrediction] = Field(default_factory=list)


class _ArtifactResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    library: _ArtifactLibrary
    inference: _ArtifactInference


class _GroundTruthAnnotation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    polygon: list[list[float]]
    holding_id: str | None = None
    book_id: str | None = None
    title: str | None = None
    author: str | None = None
    call_number: str | None = None


class _GroundTruth(BaseModel):
    model_config = ConfigDict(extra="ignore")
    annotations: list[_GroundTruthAnnotation] = Field(default_factory=list)


def cases_from_artifacts(
    result_payload: Mapping[str, Any],
    ground_truth_payload: Mapping[str, Any],
    *,
    iou_threshold: float = 0.5,
) -> list[MatchingAblationCase]:
    """Polygon-align validated artifact JSON into DB reranking cases."""
    try:
        result = _ArtifactResult.model_validate(result_payload)
        ground_truth = _GroundTruth.model_validate(ground_truth_payload)
    except ValidationError:
        return []

    cases: list[MatchingAblationCase] = []
    used_predictions: set[int] = set()
    for annotation in ground_truth.annotations:
        best_index = -1
        best_iou = 0.0
        for index, prediction in enumerate(result.inference.results):
            if index in used_predictions:
                continue
            polygon = prediction.obb_polygon
            if polygon is None and prediction.bbox is not None:
                polygon = bbox_polygon(prediction.bbox)
            if polygon is None:
                continue
            iou = polygon_iou(polygon, annotation.polygon)
            if iou > best_iou:
                best_index = index
                best_iou = iou
        if best_index < 0 or best_iou < iou_threshold:
            continue
        used_predictions.add(best_index)
        cases.append(
            MatchingAblationCase(
                library_code=result.library.code,
                run_id=result.run_id,
                ocr=result.inference.results[best_index].as_ocr_result(),
                holding_id=annotation.holding_id,
                book_id=annotation.book_id,
                title=annotation.title,
                author=annotation.author,
                call_number=annotation.call_number,
            )
        )
    return cases


def _row_identifier_matches(row: Mapping[str, Any], case: MatchingAblationCase) -> bool:
    if case.holding_id:
        return str(row.get("holding_id") or "") == case.holding_id
    if case.book_id:
        return str(row.get("book_id") or "") == case.book_id
    expected_title = normalize_core_title(case.title, case.author)
    expected_call = normalize_catalog_text(case.call_number).replace(" ", "")
    row_title = normalize_core_title(str(row.get("bookname") or ""), str(row.get("authors") or ""))
    row_call = normalize_catalog_text(str(row.get("call_number") or "")).replace(" ", "")
    return bool(expected_title and row_title == expected_title and (not expected_call or row_call == expected_call))


def score_candidate_rows(
    strategy: AblationStrategy,
    ocr: OCRResultItem,
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], float]]:
    raw_query = normalize_catalog_text(ocr.title or ocr.raw_text)
    core_query = normalize_core_title(ocr.title or ocr.raw_text, ocr.author)
    core_candidates = [
        normalize_core_title(str(row.get("normalized_bookname") or row.get("bookname") or ""), str(row.get("authors") or ""))
        for row in rows
    ]
    cosine_scores = character_ngram_tfidf_cosines(core_query, core_candidates)
    ocr_class, ocr_book_code = split_call_number(ocr.call_number or "")

    ranked: list[tuple[Mapping[str, Any], float]] = []
    for row, core_candidate, cosine in zip(rows, core_candidates, cosine_scores, strict=True):
        if strategy == "baseline":
            score = float(fuzz.token_sort_ratio(raw_query, normalize_catalog_text(str(row.get("bookname") or ""))))
        elif strategy == "preprocessed_fuzzy":
            score = float(fuzz.ratio(core_query.replace(" ", ""), core_candidate.replace(" ", "")))
        elif strategy == "tfidf":
            score = cosine * 100.0
        else:
            fuzzy_score = float(fuzz.ratio(core_query.replace(" ", ""), core_candidate.replace(" ", "")))
            title_score = (cosine * 70.0) + (fuzzy_score * 0.3)
            class_score = compute_similarity(ocr_class, str(row.get("class_no_clean") or row.get("class_no") or ""))
            book_code_score = compute_similarity(ocr_book_code, str(row.get("book_code") or ""))
            author_score = compute_similarity(ocr.author, str(row.get("normalized_authors") or row.get("authors") or ""))
            score, _ = compute_total_score(
                class_score,
                book_code_score,
                title_score,
                author_score,
                bool(ocr_class),
                has_reliable_book_code(ocr_book_code),
                has_ocr_title=bool(ocr.title),
            )
        ranked.append((row, round(score, 6)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


async def build_shadow_comparison(
    session: Any,
    library_code: str,
    ocr_results: Sequence[OCRResultItem],
    *,
    top_k: int = 3,
) -> MatchingShadowComparison:
    """Rerank each live OCR result four ways without changing production decisions."""
    from worker.services.matching_service import query_catalog_candidate_rows

    comparison_started_at = time.perf_counter()
    spines: list[ShadowSpineComparison] = []
    for ocr in ocr_results:
        rows = await query_catalog_candidate_rows(session, library_code, ocr)
        strategies: dict[AblationStrategy, ShadowStrategyResult] = {}
        for strategy in STRATEGIES:
            started_at = time.perf_counter()
            ranked = score_candidate_rows(strategy, ocr, rows)
            strategies[strategy] = ShadowStrategyResult(
                latency_ms=round((time.perf_counter() - started_at) * 1000.0, 4),
                top_candidates=[
                    ShadowCandidate(
                        rank=rank,
                        holding_id=str(row.get("holding_id") or ""),
                        book_id=str(row.get("book_id") or ""),
                        title=str(row.get("bookname") or ""),
                        author=str(row.get("authors") or ""),
                        call_number=str(row.get("call_number") or ""),
                        score=round(score, 4),
                    )
                    for rank, (row, score) in enumerate(ranked[:top_k], start=1)
                ],
            )
        spines.append(
            ShadowSpineComparison(
                detected_order=ocr.detected_order,
                candidate_pool_size=len(rows),
                strategies=strategies,
            )
        )

    return MatchingShadowComparison(
        total_latency_ms=round((time.perf_counter() - comparison_started_at) * 1000.0, 4),
        spines=spines,
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_ablation_cases(
    cases_with_rows: Sequence[tuple[MatchingAblationCase, Sequence[Mapping[str, Any]]]],
    *,
    confirmation_threshold: float = 75.0,
) -> dict[str, Any]:
    """Evaluate four rerankers on identical GT cases and candidate pools."""
    reports: dict[str, Any] = {}
    for strategy in STRATEGIES:
        evaluated = top1_correct = top3_correct = confirmed = wrong_confirmed = 0
        title_evaluated = title_correct = call_evaluated = call_correct = 0
        latencies_ms: list[float] = []
        missing_truth_from_pool = 0

        for case, rows in cases_with_rows:
            started_at = time.perf_counter()
            ranked = score_candidate_rows(strategy, case.ocr, rows)
            latencies_ms.append((time.perf_counter() - started_at) * 1000.0)
            expected_title = normalize_core_title(case.title, case.author)
            if expected_title:
                title_evaluated += 1
                title_correct += int(normalize_core_title(case.ocr.title, case.ocr.author) == expected_title)
            expected_call = normalize_catalog_text(case.call_number).replace(" ", "")
            if expected_call:
                call_evaluated += 1
                call_correct += int(normalize_catalog_text(case.ocr.call_number).replace(" ", "") == expected_call)

            if not (case.holding_id or case.book_id):
                continue
            evaluated += 1
            truth_in_pool = any(_row_identifier_matches(row, case) for row in rows)
            missing_truth_from_pool += int(not truth_in_pool)
            is_top1 = bool(ranked and _row_identifier_matches(ranked[0][0], case))
            top1_correct += int(is_top1)
            top3_correct += int(any(_row_identifier_matches(row, case) for row, _ in ranked[:3]))
            if ranked and ranked[0][1] >= confirmation_threshold:
                confirmed += 1
                wrong_confirmed += int(not is_top1)

        reports[strategy] = {
            "evaluated_count": evaluated,
            "top1_accuracy": round(top1_correct / evaluated, 6) if evaluated else 0.0,
            "top3_accuracy": round(top3_correct / evaluated, 6) if evaluated else 0.0,
            "title_normalized_accuracy": round(title_correct / title_evaluated, 6) if title_evaluated else 0.0,
            "call_number_exact_accuracy": round(call_correct / call_evaluated, 6) if call_evaluated else 0.0,
            "confirmed_count": confirmed,
            "wrong_confirmation_count": wrong_confirmed,
            "false_confirmation_rate": round(wrong_confirmed / confirmed, 6) if confirmed else 0.0,
            "candidate_pool_miss_count": missing_truth_from_pool,
            "reranking_latency_mean_ms": round(sum(latencies_ms) / len(latencies_ms), 4) if latencies_ms else 0.0,
            "reranking_latency_p95_ms": round(_percentile(latencies_ms, 0.95), 4),
        }
    return reports
