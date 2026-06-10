from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError


class ChoiceValue(BaseModel):
    model_config = ConfigDict(strict=True)

    choices: list[str]


class AnnotationResult(BaseModel):
    model_config = ConfigDict(strict=True)

    value: ChoiceValue


class Annotation(BaseModel):
    model_config = ConfigDict(strict=True)

    result: list[AnnotationResult]


class TaskData(BaseModel):
    model_config = ConfigDict(strict=True)

    area_id: str
    area_index: int
    baseline_fill_ratio: float
    crop: dict[str, int]
    delta_fill_ratio: float
    fill_ratio: float
    job_id: str
    kind: str
    local_id: str
    request_id: str
    scan: str
    template: str
    thresholds: dict[str, object]
    worker_verdict: str


class LabelStudioTask(BaseModel):
    model_config = ConfigDict(strict=True)

    annotations: list[Annotation]
    data: TaskData


CSV_FIELDNAMES = [
    "image_uri",
    "template_uri",
    "label",
    "request_id",
    "job_id",
    "area_id",
    "area_index",
    "local_id",
    "kind",
    "worker_verdict",
    "fill_ratio",
    "delta_fill_ratio",
    "baseline_fill_ratio",
]


def extract_label(task: LabelStudioTask) -> str | None:
    if not task.annotations:
        return None
    first_annotation = task.annotations[0]
    if not first_annotation.result:
        return None
    choices = first_annotation.result[0].value.choices
    if not choices:
        return None
    return choices[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Label Studio export JSON into a training manifest CSV."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to export JSON file.")
    parser.add_argument("--output", type=Path, required=True, help="Path to output CSV file.")
    parser.add_argument(
        "--kind",
        action="append",
        dest="kinds",
        help="Keep only selected task kind(s), e.g. problem or identifier. Can be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with args.input.open("r", encoding="utf-8") as fp:
        raw_tasks = json.load(fp)

    if not isinstance(raw_tasks, list):
        raise ValueError("Expected top-level JSON array.")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    label_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    skipped_invalid = 0
    skipped_missing_label = 0

    for raw_task in raw_tasks:
        try:
            task = LabelStudioTask.model_validate(raw_task)
        except ValidationError:
            skipped_invalid += 1
            continue

        label = extract_label(task)
        if label is None:
            skipped_missing_label += 1
            continue

        if args.kinds and task.data.kind not in args.kinds:
            continue

        row = {
            "image_uri": task.data.scan,
            "template_uri": task.data.template,
            "label": label,
            "request_id": task.data.request_id,
            "job_id": task.data.job_id,
            "area_id": task.data.area_id,
            "area_index": task.data.area_index,
            "local_id": task.data.local_id,
            "kind": task.data.kind,
            "worker_verdict": task.data.worker_verdict,
            "fill_ratio": task.data.fill_ratio,
            "delta_fill_ratio": task.data.delta_fill_ratio,
            "baseline_fill_ratio": task.data.baseline_fill_ratio,
        }
        rows.append(row)
        label_counts.update([label])
        kind_counts.update([task.data.kind])

    with args.output.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"input_tasks={len(raw_tasks)}")
    print(f"written_rows={len(rows)}")
    print(f"skipped_invalid={skipped_invalid}")
    print(f"skipped_missing_label={skipped_missing_label}")
    print(f"label_counts={dict(label_counts)}")
    print(f"kind_counts={dict(kind_counts)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
