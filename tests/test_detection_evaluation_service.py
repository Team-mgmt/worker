from worker.services.detection_evaluation_service import (
    PredictionPolygon,
    calculate_detection_matches,
    calculate_detection_metrics,
    calculate_detection_structure_metrics,
    calculate_placement_metrics,
    polygon_iou,
)


def rectangle(left: float, right: float) -> list[list[float]]:
    return [[left, 0], [right, 0], [right, 100], [left, 100]]


def test_structure_metrics_detect_split_spine_and_false_positive() -> None:
    predictions = [
        PredictionPolygon(polygon=rectangle(0, 50), confidence=0.9),
        PredictionPolygon(polygon=rectangle(50, 100), confidence=0.8),
        PredictionPolygon(polygon=rectangle(200, 230), confidence=0.7),
    ]

    metrics = calculate_detection_structure_metrics(predictions, [rectangle(0, 100)])

    assert metrics.split_ground_truth_count == 1
    assert metrics.correct_ground_truth_count == 0
    assert metrics.merged_prediction_count == 0
    assert metrics.false_positive_prediction_count == 1
    assert metrics.split_rate == 1.0


def test_structure_metrics_detect_merged_prediction() -> None:
    predictions = [PredictionPolygon(polygon=rectangle(0, 200), confidence=0.9)]

    metrics = calculate_detection_structure_metrics(
        predictions,
        [rectangle(0, 100), rectangle(100, 200)],
    )

    assert metrics.merged_prediction_count == 1
    assert metrics.merged_ground_truth_count == 2
    assert metrics.correct_ground_truth_count == 0
    assert metrics.merge_rate == 1.0


def test_structure_metrics_separate_correct_and_missed_spines() -> None:
    predictions = [PredictionPolygon(polygon=rectangle(0, 100), confidence=0.9)]

    metrics = calculate_detection_structure_metrics(
        predictions,
        [rectangle(0, 100), rectangle(110, 210)],
    )

    assert metrics.correct_ground_truth_count == 1
    assert metrics.missed_ground_truth_count == 1
    assert metrics.split_ground_truth_count == 0


def square(left: float, top: float, right: float, bottom: float) -> list[list[float]]:
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_polygon_iou_for_identical_and_disjoint_shapes() -> None:
    assert polygon_iou(square(0, 0, 10, 10), square(0, 0, 10, 10)) == 1.0
    assert polygon_iou(square(0, 0, 10, 10), square(20, 20, 30, 30)) == 0.0


def test_duplicate_prediction_is_counted_as_false_positive() -> None:
    targets = [square(0, 0, 10, 100), square(20, 0, 30, 100)]
    predictions = [
        PredictionPolygon(targets[0], 0.95),
        PredictionPolygon(targets[1], 0.90),
        PredictionPolygon(targets[1], 0.40),
    ]

    metrics = calculate_detection_metrics(predictions, targets)

    assert metrics.true_positive == 2
    assert metrics.false_positive == 1
    assert metrics.false_negative == 0
    assert metrics.precision == 0.666667
    assert metrics.recall == 1.0
    assert metrics.ap50 == 1.0
    assert metrics.count_error == 1


def test_detection_matches_expose_per_spine_iou_and_false_positives() -> None:
    target = square(0, 0, 10, 100)
    duplicate = square(0, 0, 5, 100)
    predictions = [PredictionPolygon(target, 0.9), PredictionPolygon(duplicate, 0.5)]

    matches = calculate_detection_matches(
        predictions,
        [{"id": "spine-1", "polygon": target}],
    )

    assert matches[0].status == "matched"
    assert matches[0].ground_truth_id == "spine-1"
    assert matches[0].iou == 1.0
    assert matches[1].status == "false_positive"


def test_placement_metrics_compare_decisions_after_polygon_matching() -> None:
    first = square(0, 0, 10, 100)
    second = square(20, 0, 30, 100)
    predictions = [
        PredictionPolygon(first, 0.95, "normal"),
        PredictionPolygon(second, 0.90, "suspected_misplacement"),
    ]
    annotations = [
        {"polygon": first, "placement_status": "normal"},
        {"polygon": second, "placement_status": "misplaced"},
    ]

    metrics = calculate_placement_metrics(predictions, annotations)

    assert metrics is not None
    assert metrics.evaluated_count == 2
    assert metrics.true_positive == 1
    assert metrics.true_negative == 1
    assert metrics.false_positive == 0
    assert metrics.false_negative == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_placement_metrics_are_omitted_without_placement_labels() -> None:
    assert calculate_placement_metrics([], [{"polygon": square(0, 0, 10, 100)}]) is None
