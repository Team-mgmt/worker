from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


LABEL_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}

WORKER_VERDICT_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}


@dataclass(frozen=True)
class Row:
    label: int
    fill_ratio: float
    delta_fill_ratio: float
    baseline_fill_ratio: float
    worker_verdict: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate simple threshold baselines and current worker verdict.")
    parser.add_argument("--val-csv", type=Path, required=True)
    parser.add_argument("--test-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--s3-backup-uri", type=str, default=None)
    return parser.parse_args()


def load_rows(csv_path: Path) -> list[Row]:
    rows: list[Row] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            rows.append(
                Row(
                    label=LABEL_TO_INDEX[row["label"]],
                    fill_ratio=float(row["fill_ratio"]),
                    delta_fill_ratio=float(row["delta_fill_ratio"]),
                    baseline_fill_ratio=float(row["baseline_fill_ratio"]),
                    worker_verdict=WORKER_VERDICT_TO_INDEX[row["worker_verdict"]],
                )
            )
    return rows


def evaluate(y_true: list[int], y_pred: list[int]) -> dict[str, float]:
    tp = sum(1 for target, pred in zip(y_true, y_pred, strict=True) if target == 1 and pred == 1)
    tn = sum(1 for target, pred in zip(y_true, y_pred, strict=True) if target == 0 and pred == 0)
    fp = sum(1 for target, pred in zip(y_true, y_pred, strict=True) if target == 0 and pred == 1)
    fn = sum(1 for target, pred in zip(y_true, y_pred, strict=True) if target == 1 and pred == 0)
    total = max(len(y_true), 1)
    accuracy = (tp + tn) / total
    filled_precision = tp / max(tp + fp, 1)
    filled_recall = tp / max(tp + fn, 1)
    filled_f1 = 0.0
    if filled_precision + filled_recall > 0:
        filled_f1 = 2 * filled_precision * filled_recall / (filled_precision + filled_recall)
    return {
        "accuracy": accuracy,
        "filled_precision": filled_precision,
        "filled_recall": filled_recall,
        "filled_f1": filled_f1,
    }


def predict_worker_verdict(rows: list[Row]) -> list[int]:
    return [row.worker_verdict for row in rows]


def predict_fill_ratio_threshold(rows: list[Row], threshold: float) -> list[int]:
    return [1 if row.fill_ratio >= threshold else 0 for row in rows]


def predict_delta_fill_ratio_threshold(rows: list[Row], threshold: float) -> list[int]:
    return [1 if row.delta_fill_ratio >= threshold else 0 for row in rows]


def find_best_threshold(
    rows: list[Row],
    threshold_candidates: list[float],
    predictor: callable,
) -> tuple[float, dict[str, float]]:
    y_true = [row.label for row in rows]
    best_threshold = threshold_candidates[0]
    best_metrics = evaluate(y_true, predictor(rows, best_threshold))
    for threshold in threshold_candidates[1:]:
        metrics = evaluate(y_true, predictor(rows, threshold))
        if metrics["filled_f1"] > best_metrics["filled_f1"]:
            best_threshold = threshold
            best_metrics = metrics
    return best_threshold, best_metrics


def sync_dir_to_s3(local_dir: Path, s3_uri: str) -> None:
    subprocess.run(["aws", "s3", "cp", str(local_dir), s3_uri, "--recursive"], check=True)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    val_rows = load_rows(args.val_csv)
    test_rows = load_rows(args.test_csv)
    y_test = [row.label for row in test_rows]

    threshold_candidates = [candidate / 1000 for candidate in range(0, 1001)]

    worker_metrics = evaluate(y_test, predict_worker_verdict(test_rows))
    fill_threshold, fill_val_metrics = find_best_threshold(val_rows, threshold_candidates, predict_fill_ratio_threshold)
    delta_threshold, delta_val_metrics = find_best_threshold(val_rows, threshold_candidates, predict_delta_fill_ratio_threshold)
    fill_test_metrics = evaluate(y_test, predict_fill_ratio_threshold(test_rows, fill_threshold))
    delta_test_metrics = evaluate(y_test, predict_delta_fill_ratio_threshold(test_rows, delta_threshold))

    metrics = {
        "worker_verdict_test_metrics": worker_metrics,
        "fill_ratio_threshold": fill_threshold,
        "fill_ratio_val_metrics": fill_val_metrics,
        "fill_ratio_test_metrics": fill_test_metrics,
        "delta_fill_ratio_threshold": delta_threshold,
        "delta_fill_ratio_val_metrics": delta_val_metrics,
        "delta_fill_ratio_test_metrics": delta_test_metrics,
    }

    metrics_path = args.output_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as fp:
        json.dump(metrics, fp, ensure_ascii=False, indent=2)

    if args.s3_backup_uri:
        sync_dir_to_s3(args.output_dir, args.s3_backup_uri)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
