from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from worker.schemas.artifact_evaluation import DetectionMetrics, DetectionStructureMetrics, PlacementMetrics


@dataclass(frozen=True)
class PredictionPolygon:
    polygon: list[list[float]]
    confidence: float
    decision: str | None = None


def bbox_polygon(bbox: list[float]) -> list[list[float]]:
    left, top, right, bottom = bbox
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def polygon_iou(first: list[list[float]], second: list[list[float]]) -> float:
    first_points = cv2.convexHull(np.asarray(first, dtype=np.float32))
    second_points = cv2.convexHull(np.asarray(second, dtype=np.float32))
    first_area = abs(float(cv2.contourArea(first_points)))
    second_area = abs(float(cv2.contourArea(second_points)))
    if first_area <= 0 or second_area <= 0:
        return 0.0
    intersection_area, _ = cv2.intersectConvexConvex(first_points, second_points)
    union_area = first_area + second_area - float(intersection_area)
    return max(0.0, min(1.0, float(intersection_area) / union_area)) if union_area > 0 else 0.0


def polygon_overlap_coverages(
    first: list[list[float]],
    second: list[list[float]],
) -> tuple[float, float]:
    """Return intersection coverage for the smaller and larger polygon."""

    first_points = cv2.convexHull(np.asarray(first, dtype=np.float32))
    second_points = cv2.convexHull(np.asarray(second, dtype=np.float32))
    first_area = abs(float(cv2.contourArea(first_points)))
    second_area = abs(float(cv2.contourArea(second_points)))
    if first_area <= 0 or second_area <= 0:
        return 0.0, 0.0
    intersection_area, _ = cv2.intersectConvexConvex(first_points, second_points)
    smaller_area = min(first_area, second_area)
    larger_area = max(first_area, second_area)
    return (
        max(0.0, min(1.0, float(intersection_area) / smaller_area)),
        max(0.0, min(1.0, float(intersection_area) / larger_area)),
    )


def calculate_detection_structure_metrics(
    predictions: list[PredictionPolygon],
    ground_truth: list[list[list[float]]],
    minimum_small_polygon_coverage: float = 0.5,
    minimum_large_polygon_coverage: float = 0.1,
) -> DetectionStructureMetrics:
    """Classify polygon relationships as correct, split, merged, missed, or false positive."""

    prediction_to_ground_truth: list[set[int]] = [set() for _ in predictions]
    ground_truth_to_predictions: list[set[int]] = [set() for _ in ground_truth]
    for prediction_index, prediction in enumerate(predictions):
        for ground_truth_index, target in enumerate(ground_truth):
            smaller_coverage, larger_coverage = polygon_overlap_coverages(prediction.polygon, target)
            if (
                smaller_coverage >= minimum_small_polygon_coverage
                and larger_coverage >= minimum_large_polygon_coverage
            ):
                prediction_to_ground_truth[prediction_index].add(ground_truth_index)
                ground_truth_to_predictions[ground_truth_index].add(prediction_index)

    merged_prediction_indices = {
        index for index, matches in enumerate(prediction_to_ground_truth) if len(matches) >= 2
    }
    correct_count = split_count = merged_ground_truth_count = missed_count = 0
    for matches in ground_truth_to_predictions:
        if not matches:
            missed_count += 1
        elif len(matches) >= 2:
            split_count += 1
        elif next(iter(matches)) in merged_prediction_indices:
            merged_ground_truth_count += 1
        else:
            correct_count += 1

    false_positive_count = sum(1 for matches in prediction_to_ground_truth if not matches)
    ground_truth_count = len(ground_truth)
    prediction_count = len(predictions)
    return DetectionStructureMetrics(
        ground_truth_count=ground_truth_count,
        prediction_count=prediction_count,
        correct_ground_truth_count=correct_count,
        split_ground_truth_count=split_count,
        merged_ground_truth_count=merged_ground_truth_count,
        missed_ground_truth_count=missed_count,
        merged_prediction_count=len(merged_prediction_indices),
        false_positive_prediction_count=false_positive_count,
        split_rate=round(split_count / ground_truth_count, 6) if ground_truth_count else 0.0,
        merge_rate=round(len(merged_prediction_indices) / prediction_count, 6) if prediction_count else 0.0,
        minimum_small_polygon_coverage=minimum_small_polygon_coverage,
        minimum_large_polygon_coverage=minimum_large_polygon_coverage,
    )


def predictions_from_result(result: dict) -> list[PredictionPolygon]:
    predictions: list[PredictionPolygon] = []
    for item in result.get("inference", {}).get("results", []):
        polygon = item.get("obb_polygon")
        if not polygon and item.get("bbox") and len(item["bbox"]) == 4:
            polygon = bbox_polygon(item["bbox"])
        if polygon and len(polygon) == 4:
            predictions.append(
                PredictionPolygon(
                    polygon=polygon,
                    confidence=float(item.get("detection_confidence") or 0.0),
                    decision=item.get("decision"),
                )
            )
    return predictions


def calculate_detection_metrics(
    predictions: list[PredictionPolygon],
    ground_truth: list[list[list[float]]],
    iou_threshold: float = 0.5,
) -> DetectionMetrics:
    ordered_predictions = sorted(predictions, key=lambda item: item.confidence, reverse=True)
    matched_ground_truth: set[int] = set()
    true_positive_flags: list[int] = []
    false_positive_flags: list[int] = []
    matched_ious: list[float] = []

    for prediction in ordered_predictions:
        best_index = -1
        best_iou = 0.0
        for index, target in enumerate(ground_truth):
            if index in matched_ground_truth:
                continue
            iou = polygon_iou(prediction.polygon, target)
            if iou > best_iou:
                best_index = index
                best_iou = iou

        if best_index >= 0 and best_iou >= iou_threshold:
            matched_ground_truth.add(best_index)
            true_positive_flags.append(1)
            false_positive_flags.append(0)
            matched_ious.append(best_iou)
        else:
            true_positive_flags.append(0)
            false_positive_flags.append(1)

    true_positive = sum(true_positive_flags)
    false_positive = sum(false_positive_flags)
    false_negative = len(ground_truth) - true_positive
    precision = true_positive / (true_positive + false_positive) if ordered_predictions else 0.0
    recall = true_positive / len(ground_truth) if ground_truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

    ap50 = 0.0
    if ground_truth and ordered_predictions:
        cumulative_tp = np.cumsum(true_positive_flags)
        cumulative_fp = np.cumsum(false_positive_flags)
        recalls = cumulative_tp / len(ground_truth)
        precisions = cumulative_tp / np.maximum(cumulative_tp + cumulative_fp, 1)
        ap50 = float(
            np.mean(
                [
                    max((float(value) for value, recall_value in zip(precisions, recalls, strict=True) if recall_value >= threshold), default=0.0)
                    for threshold in np.linspace(0.0, 1.0, 101)
                ]
            )
        )

    return DetectionMetrics(
        iou_threshold=iou_threshold,
        ground_truth_count=len(ground_truth),
        prediction_count=len(ordered_predictions),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        ap50=round(ap50, 6),
        mean_matched_iou=round(sum(matched_ious) / len(matched_ious), 6) if matched_ious else 0.0,
        count_error=len(ordered_predictions) - len(ground_truth),
    )


def calculate_placement_metrics(
    predictions: list[PredictionPolygon],
    annotations: list[dict],
    iou_threshold: float = 0.5,
) -> PlacementMetrics | None:
    """Evaluate misplaced-vs-normal decisions against polygon-aligned GT labels."""

    labeled_annotations = [annotation for annotation in annotations if annotation.get("placement_status") in {"normal", "misplaced"}]
    if not labeled_annotations:
        return None

    matched_predictions: set[int] = set()
    true_positive = false_positive = false_negative = true_negative = 0
    for annotation in labeled_annotations:
        best_index = -1
        best_iou = 0.0
        for index, prediction in enumerate(predictions):
            if index in matched_predictions:
                continue
            iou = polygon_iou(prediction.polygon, annotation["polygon"])
            if iou > best_iou:
                best_index = index
                best_iou = iou

        predicted_misplaced = False
        if best_index >= 0 and best_iou >= iou_threshold:
            matched_predictions.add(best_index)
            predicted_misplaced = predictions[best_index].decision == "suspected_misplacement"

        actual_misplaced = annotation["placement_status"] == "misplaced"
        if actual_misplaced and predicted_misplaced:
            true_positive += 1
        elif actual_misplaced:
            false_negative += 1
        elif predicted_misplaced:
            false_positive += 1
        else:
            true_negative += 1

    false_positive += sum(
        1
        for index, prediction in enumerate(predictions)
        if index not in matched_predictions and prediction.decision == "suspected_misplacement"
    )
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return PlacementMetrics(
        evaluated_count=len(labeled_annotations),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
    )
