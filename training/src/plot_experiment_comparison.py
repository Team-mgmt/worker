from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns


LABEL_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}


@dataclass(frozen=True)
class ExperimentMetrics:
    name: str
    accuracy: float
    filled_precision: float
    filled_recall: float
    filled_f1: float


@dataclass(frozen=True)
class ConfusionCounts:
    tn: int
    fp: int
    fn: int
    tp: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create confusion matrix comparison plots from experiment metrics.")
    parser.add_argument("--test-csv", type=Path, required=True)
    parser.add_argument(
        "--experiment-metrics",
        action="append",
        default=[],
        help="Experiment descriptor in NAME=PATH form. PATH can be local or s3://.../metrics.json",
    )
    parser.add_argument(
        "--threshold-metrics",
        type=str,
        default=None,
        help="Optional threshold baseline metrics.json path (local or s3://). Adds worker/fill_ratio/delta_fill_ratio baselines.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--s3-backup-uri", type=str, default=None)
    return parser.parse_args()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Unsupported S3 URI: {uri}")
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return bucket, key


def resolve_path(path_or_s3: str, output_dir: Path) -> Path:
    if not path_or_s3.startswith("s3://"):
        return Path(path_or_s3)
    _, key = parse_s3_uri(path_or_s3)
    destination = output_dir / "downloaded" / Path(key).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["aws", "s3", "cp", path_or_s3, str(destination)], check=True)
    return destination


def load_test_supports(csv_path: Path) -> tuple[int, int]:
    negatives = 0
    positives = 0
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            label = LABEL_TO_INDEX[row["label"]]
            if label == 1:
                positives += 1
            else:
                negatives += 1
    return negatives, positives


def load_metrics_from_experiment_json(name: str, json_path: Path) -> ExperimentMetrics:
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    metrics = payload["test_metrics"]
    return ExperimentMetrics(
        name=name,
        accuracy=float(metrics["accuracy"]),
        filled_precision=float(metrics["filled_precision"]),
        filled_recall=float(metrics["filled_recall"]),
        filled_f1=float(metrics["filled_f1"]),
    )


def load_metrics_from_threshold_json(json_path: Path) -> list[ExperimentMetrics]:
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    return [
        ExperimentMetrics(
            name="worker_verdict",
            accuracy=float(payload["worker_verdict_test_metrics"]["accuracy"]),
            filled_precision=float(payload["worker_verdict_test_metrics"]["filled_precision"]),
            filled_recall=float(payload["worker_verdict_test_metrics"]["filled_recall"]),
            filled_f1=float(payload["worker_verdict_test_metrics"]["filled_f1"]),
        ),
        ExperimentMetrics(
            name=f"fill_ratio_threshold_{payload['fill_ratio_threshold']:.3f}",
            accuracy=float(payload["fill_ratio_test_metrics"]["accuracy"]),
            filled_precision=float(payload["fill_ratio_test_metrics"]["filled_precision"]),
            filled_recall=float(payload["fill_ratio_test_metrics"]["filled_recall"]),
            filled_f1=float(payload["fill_ratio_test_metrics"]["filled_f1"]),
        ),
        ExperimentMetrics(
            name=f"delta_fill_ratio_threshold_{payload['delta_fill_ratio_threshold']:.3f}",
            accuracy=float(payload["delta_fill_ratio_test_metrics"]["accuracy"]),
            filled_precision=float(payload["delta_fill_ratio_test_metrics"]["filled_precision"]),
            filled_recall=float(payload["delta_fill_ratio_test_metrics"]["filled_recall"]),
            filled_f1=float(payload["delta_fill_ratio_test_metrics"]["filled_f1"]),
        ),
    ]


def close_enough(actual: float, expected: float, tolerance: float = 1e-9) -> bool:
    return abs(actual - expected) <= tolerance


def reconstruct_confusion_counts(metrics: ExperimentMetrics, negatives: int, positives: int) -> ConfusionCounts:
    total = negatives + positives
    for tp in range(positives + 1):
        fn = positives - tp
        for fp in range(negatives + 1):
            tn = negatives - fp
            accuracy = (tp + tn) / max(total, 1)
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 0.0
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            if (
                close_enough(accuracy, metrics.accuracy)
                and close_enough(precision, metrics.filled_precision)
                and close_enough(recall, metrics.filled_recall)
                and close_enough(f1, metrics.filled_f1)
            ):
                return ConfusionCounts(tn=tn, fp=fp, fn=fn, tp=tp)
    raise ValueError(f"Could not reconstruct confusion counts for experiment: {metrics.name}")


def sync_dir_to_s3(local_dir: Path, s3_uri: str) -> None:
    subprocess.run(["aws", "s3", "cp", str(local_dir), s3_uri, "--recursive"], check=True)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    negatives, positives = load_test_supports(args.test_csv)
    experiments: list[ExperimentMetrics] = []

    for raw_experiment in args.experiment_metrics:
        name, separator, path_or_s3 = raw_experiment.partition("=")
        if not separator or not name or not path_or_s3:
            raise ValueError(f"Invalid --experiment-metrics value: {raw_experiment}")
        metrics_path = resolve_path(path_or_s3, args.output_dir)
        experiments.append(load_metrics_from_experiment_json(name, metrics_path))

    if args.threshold_metrics:
        threshold_metrics_path = resolve_path(args.threshold_metrics, args.output_dir)
        experiments.extend(load_metrics_from_threshold_json(threshold_metrics_path))

    if not experiments:
        raise ValueError("No experiments provided.")

    confusion_counts_by_name: dict[str, ConfusionCounts] = {}
    for experiment in experiments:
        confusion_counts_by_name[experiment.name] = reconstruct_confusion_counts(experiment, negatives=negatives, positives=positives)

    summary_rows: list[dict[str, str | int | float]] = []
    for experiment in experiments:
        counts = confusion_counts_by_name[experiment.name]
        summary_rows.append(
            {
                "name": experiment.name,
                "accuracy": experiment.accuracy,
                "filled_precision": experiment.filled_precision,
                "filled_recall": experiment.filled_recall,
                "filled_f1": experiment.filled_f1,
                "tn": counts.tn,
                "fp": counts.fp,
                "fn": counts.fn,
                "tp": counts.tp,
            }
        )

    summary_json_path = args.output_dir / "comparison_summary.json"
    with summary_json_path.open("w", encoding="utf-8") as fp:
        json.dump(
            {
                "test_support": {
                    "not_filled": negatives,
                    "filled": positives,
                },
                "experiments": summary_rows,
            },
            fp,
            ensure_ascii=False,
            indent=2,
        )

    summary_csv_path = args.output_dir / "comparison_summary.csv"
    with summary_csv_path.open("w", encoding="utf-8", newline="") as fp:
        fieldnames = ["name", "accuracy", "filled_precision", "filled_recall", "filled_f1", "tn", "fp", "fn", "tp"]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    sns.set_theme(style="white")
    columns = 3
    rows = math.ceil(len(experiments) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(columns * 5, rows * 4))
    axes_list = axes.flatten().tolist() if hasattr(axes, "flatten") else [axes]

    for axis, experiment in zip(axes_list, experiments, strict=False):
        counts = confusion_counts_by_name[experiment.name]
        matrix = np.array([[counts.tn, counts.fp], [counts.fn, counts.tp]])  # type: ignore[name-defined]
        sns.heatmap(
            matrix,
            annot=True,
            fmt="d",
            cmap="Blues",
            cbar=False,
            ax=axis,
            xticklabels=["pred_not_filled", "pred_filled"],
            yticklabels=["true_not_filled", "true_filled"],
        )
        axis.set_title(
            f"{experiment.name}\n"
            f"acc={experiment.accuracy:.4f} recall={experiment.filled_recall:.4f}\n"
            f"f1={experiment.filled_f1:.4f}"
        )
        axis.set_xlabel("")
        axis.set_ylabel("")

    for axis in axes_list[len(experiments) :]:
        axis.axis("off")

    fig.tight_layout()
    plot_path = args.output_dir / "confusion_matrix_comparison.png"
    fig.savefig(plot_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    if args.s3_backup_uri:
        sync_dir_to_s3(args.output_dir, args.s3_backup_uri)

    print(json.dumps({"output_dir": str(args.output_dir), "plot_path": str(plot_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import numpy as np

    raise SystemExit(main())
