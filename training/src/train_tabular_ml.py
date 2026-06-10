from __future__ import annotations

import argparse
import csv
import json
import pickle
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


LABEL_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}

WORKER_VERDICT_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}


@dataclass(frozen=True)
class TabularRow:
    label: int
    fill_ratio: float
    delta_fill_ratio: float
    baseline_fill_ratio: float
    area_index: int
    worker_verdict: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a tabular ML baseline for bubble classification.")
    parser.add_argument("--train-csv", type=Path, required=True)
    parser.add_argument("--val-csv", type=Path, required=True)
    parser.add_argument("--test-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", choices=("logistic_regression", "random_forest"), required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--include-worker-verdict",
        action="store_true",
        help="Include worker_verdict as a categorical feature. Disabled by default to avoid target proxy leakage.",
    )
    parser.add_argument("--s3-backup-uri", type=str, default=None)
    return parser.parse_args()


def load_manifest(csv_path: Path) -> list[TabularRow]:
    rows: list[TabularRow] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            label_name = row["label"]
            if label_name not in LABEL_TO_INDEX:
                raise ValueError(f"Unknown label: {label_name}")
            rows.append(
                TabularRow(
                    label=LABEL_TO_INDEX[label_name],
                    fill_ratio=float(row["fill_ratio"]),
                    delta_fill_ratio=float(row["delta_fill_ratio"]),
                    baseline_fill_ratio=float(row["baseline_fill_ratio"]),
                    area_index=int(row["area_index"]),
                    worker_verdict=row["worker_verdict"],
                )
            )
    return rows


def build_xy(rows: list[TabularRow], include_worker_verdict: bool) -> tuple[np.ndarray, np.ndarray]:
    if include_worker_verdict:
        x = np.array(
            [
                [
                    row.fill_ratio,
                    row.delta_fill_ratio,
                    row.baseline_fill_ratio,
                    row.area_index,
                    row.worker_verdict,
                ]
                for row in rows
            ],
            dtype=object,
        )
    else:
        x = np.array(
            [
                [
                    row.fill_ratio,
                    row.delta_fill_ratio,
                    row.baseline_fill_ratio,
                    row.area_index,
                ]
                for row in rows
            ],
            dtype=object,
        )
    y = np.array([row.label for row in rows], dtype=np.int64)
    return x, y


def build_model(model_name: str, seed: int, include_worker_verdict: bool) -> Pipeline:
    transformers: list[tuple[str, Pipeline, list[int]]] = [
        (
            "numeric",
            Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]
            ),
            [0, 1, 2, 3],
        ),
    ]
    if include_worker_verdict:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                [4],
            )
        )

    preprocessor = ColumnTransformer(transformers=transformers)

    if model_name == "logistic_regression":
        estimator = LogisticRegression(
            max_iter=1000,
            random_state=seed,
            class_weight="balanced",
        )
    elif model_name == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=300,
            random_state=seed,
            class_weight="balanced",
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Unsupported model: {model_name}")

    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("estimator", estimator),
        ]
    )


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())

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


def sync_dir_to_s3(local_dir: Path, s3_uri: str) -> None:
    subprocess.run(["aws", "s3", "cp", str(local_dir), s3_uri, "--recursive"], check=True)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    train_rows = load_manifest(args.train_csv)
    val_rows = load_manifest(args.val_csv)
    test_rows = load_manifest(args.test_csv)

    x_train, y_train = build_xy(train_rows, include_worker_verdict=args.include_worker_verdict)
    x_val, y_val = build_xy(val_rows, include_worker_verdict=args.include_worker_verdict)
    x_test, y_test = build_xy(test_rows, include_worker_verdict=args.include_worker_verdict)

    model = build_model(args.model, args.seed, include_worker_verdict=args.include_worker_verdict)
    model.fit(x_train, y_train)

    val_pred = model.predict(x_val)
    test_pred = model.predict(x_test)
    val_metrics = evaluate(y_val, val_pred)
    test_metrics = evaluate(y_test, test_pred)

    model_path = args.output_dir / "model.pkl"
    with model_path.open("wb") as fp:
        pickle.dump(model, fp)

    metrics_path = args.output_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as fp:
        json.dump(
            {
                "model": args.model,
                "features": (
                    [
                        "fill_ratio",
                        "delta_fill_ratio",
                        "baseline_fill_ratio",
                        "area_index",
                        "worker_verdict",
                    ]
                    if args.include_worker_verdict
                    else [
                        "fill_ratio",
                        "delta_fill_ratio",
                        "baseline_fill_ratio",
                        "area_index",
                    ]
                ),
                "train_rows": len(train_rows),
                "val_rows": len(val_rows),
                "test_rows": len(test_rows),
                "val_metrics": val_metrics,
                "test_metrics": test_metrics,
            },
            fp,
            ensure_ascii=False,
            indent=2,
        )

    if args.s3_backup_uri:
        sync_dir_to_s3(args.output_dir, args.s3_backup_uri)

    print(json.dumps({"model": args.model, "val_metrics": val_metrics, "test_metrics": test_metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
