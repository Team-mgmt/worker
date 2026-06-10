from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from statistics import median

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect width/height distribution for local PNG files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing PNG files to inspect.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    png_paths = sorted(args.input_dir.rglob("*.png"))
    if not png_paths:
        print("inspected=0")
        return 0

    widths: list[int] = []
    heights: list[int] = []
    pair_counts: Counter[tuple[int, int]] = Counter()

    for path in png_paths:
        with Image.open(path) as image:
            width, height = image.size
        widths.append(width)
        heights.append(height)
        pair_counts.update([(width, height)])

    print(f"inspected={len(png_paths)}")
    print(f"width_min={min(widths)}")
    print(f"width_median={median(widths)}")
    print(f"width_max={max(widths)}")
    print(f"height_min={min(heights)}")
    print(f"height_median={median(heights)}")
    print(f"height_max={max(heights)}")
    print(f"most_common_sizes={pair_counts.most_common(10)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
