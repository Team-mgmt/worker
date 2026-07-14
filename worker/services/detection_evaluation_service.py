from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from worker.schemas.artifact_evaluation import DetectionMetrics


@dataclass(frozen=True)
class PredictionPolygon:
    polygon: list[list[float]]
    confidence: float


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
