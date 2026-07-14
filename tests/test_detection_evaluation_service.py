from worker.services.detection_evaluation_service import PredictionPolygon, calculate_detection_metrics, polygon_iou


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
