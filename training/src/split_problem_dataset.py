from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split a manifest CSV into train/val/test by request_id."
    )
    parser.add_argument("--input", type=Path, required=True, help="Input manifest CSV.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write split CSV files.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train ratio.")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--prefix", type=str, default="project-2-problem", help="Output file prefix.")
    return parser.parse_args()


def assign_request_ids(request_ids: list[str], train_ratio: float, val_ratio: float, seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    request_ids = request_ids[:]
    rng.shuffle(request_ids)

    total = len(request_ids)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)

    split_by_request: dict[str, str] = {}
    for index, request_id in enumerate(request_ids):
        if index < train_end:
            split_by_request[request_id] = "train"
        elif index < val_end:
            split_by_request[request_id] = "val"
        else:
            split_by_request[request_id] = "test"
    return split_by_request


def main() -> int:
    args = parse_args()

    if args.train_ratio <= 0 or args.val_ratio <= 0 or args.train_ratio + args.val_ratio >= 1:
        raise ValueError("Ratios must satisfy train_ratio > 0, val_ratio > 0, and train_ratio + val_ratio < 1.")

    with args.input.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError("Input CSV is missing a header row.")
        rows = list(reader)

    request_ids = sorted({row["request_id"] for row in rows})
    split_by_request = assign_request_ids(
        request_ids=request_ids,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )

    rows_by_split: dict[str, list[dict[str, str]]] = defaultdict(list)
    label_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        split = split_by_request[row["request_id"]]
        rows_by_split[split].append(row)
        label_counts[split].update([row["label"]])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split_name in ("train", "val", "test"):
        output_path = args.output_dir / f"{args.prefix}-{split_name}.csv"
        with output_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_by_split[split_name])

    print(f"input_rows={len(rows)}")
    print(f"unique_request_ids={len(request_ids)}")
    for split_name in ("train", "val", "test"):
        print(
            f"{split_name}_rows={len(rows_by_split[split_name])} "
            f"{split_name}_request_ids={sum(1 for split in split_by_request.values() if split == split_name)} "
            f"{split_name}_labels={dict(label_counts[split_name])}"
        )
    print(f"output_dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
