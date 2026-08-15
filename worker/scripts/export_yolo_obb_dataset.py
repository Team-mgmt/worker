from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

SUPPORTED_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True)
class ExportItem:
    ground_truth_path: Path
    image_path: Path


def yolo_obb_lines(ground_truth: dict[str, Any], image_width: int, image_height: int) -> list[str]:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive.")

    lines: list[str] = []
    for index, annotation in enumerate(ground_truth.get("annotations") or [], start=1):
        polygon = annotation.get("polygon")
        if not isinstance(polygon, list) or len(polygon) != 4:
            raise ValueError(f"Annotation {index} must contain exactly four polygon points.")

        coordinates: list[str] = []
        for point in polygon:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(f"Annotation {index} contains an invalid polygon point.")
            x, y = float(point[0]), float(point[1])
            if not (0 <= x <= image_width and 0 <= y <= image_height):
                raise ValueError(f"Annotation {index} is outside the image boundary.")
            coordinates.extend((f"{x / image_width:.6f}", f"{y / image_height:.6f}"))
        lines.append("0 " + " ".join(coordinates))
    return lines


def find_sibling_image(ground_truth_path: Path, ground_truth: dict[str, Any]) -> Path:
    image_key = str((ground_truth.get("image") or {}).get("key") or "")
    if image_key:
        keyed_image = ground_truth_path.parent / Path(image_key).name
        if keyed_image.is_file():
            return keyed_image
    for suffix in SUPPORTED_IMAGE_SUFFIXES:
        candidate = ground_truth_path.parent / f"original{suffix}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No original image beside {ground_truth_path}")


def discover_items(artifact_root: Path) -> list[ExportItem]:
    items: list[ExportItem] = []
    for ground_truth_path in sorted(artifact_root.rglob("ground-truth.json")):
        ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
        items.append(ExportItem(ground_truth_path, find_sibling_image(ground_truth_path, ground_truth)))
    return items


def export_item(item: ExportItem, output_dir: Path, split: str) -> dict[str, Any]:
    ground_truth = json.loads(item.ground_truth_path.read_text(encoding="utf-8"))
    with Image.open(item.image_path) as image:
        actual_width, actual_height = image.size

    recorded_image = ground_truth.get("image") or {}
    recorded_width = int(recorded_image.get("width") or actual_width)
    recorded_height = int(recorded_image.get("height") or actual_height)
    if (recorded_width, recorded_height) != (actual_width, actual_height):
        raise ValueError(
            f"Image size mismatch for {item.ground_truth_path}: "
            f"GT={recorded_width}x{recorded_height}, actual={actual_width}x{actual_height}"
        )

    run_id = str(ground_truth.get("run_id") or item.ground_truth_path.parent.name)
    stem = run_id.replace("/", "-").replace("\\", "-")
    image_output = output_dir / "images" / split / f"{stem}{item.image_path.suffix.lower()}"
    label_output = output_dir / "labels" / split / f"{stem}.txt"
    image_output.parent.mkdir(parents=True, exist_ok=True)
    label_output.parent.mkdir(parents=True, exist_ok=True)

    lines = yolo_obb_lines(ground_truth, actual_width, actual_height)
    shutil.copy2(item.image_path, image_output)
    label_output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return {
        "run_id": run_id,
        "source_ground_truth": str(item.ground_truth_path),
        "source_image": str(item.image_path),
        "image": str(image_output.relative_to(output_dir)).replace("\\", "/"),
        "label": str(label_output.relative_to(output_dir)).replace("\\", "/"),
        "annotation_count": len(lines),
        "width": actual_width,
        "height": actual_height,
        "split": split,
    }


def write_metadata(output_dir: Path, manifest: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    existing_items: list[dict[str, Any]] = []
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_items = list(existing.get("items") or [])
    items_by_image = {item["image"]: item for item in existing_items}
    items_by_image.update({item["image"]: item for item in manifest})

    (output_dir / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: book_spine\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "format": "yolo-obb",
                "class_names": ["book_spine"],
                "items": list(items_by_image.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export reviewed ShelfAlign GT as a YOLO OBB dataset.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact-root", type=Path, help="Folder containing run ground-truth.json and original images.")
    source.add_argument("--ground-truth", type=Path, help="A single ground-truth.json file.")
    parser.add_argument("--image", type=Path, help="Original image for --ground-truth; otherwise a sibling original.* is used.")
    parser.add_argument("--output", type=Path, required=True, help="YOLO dataset output directory.")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ground_truth:
        ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        image_path = args.image or find_sibling_image(args.ground_truth, ground_truth)
        items = [ExportItem(args.ground_truth, image_path)]
    else:
        if args.image:
            raise SystemExit("--image can only be used with --ground-truth.")
        items = discover_items(args.artifact_root)

    if not items:
        raise SystemExit("No exportable ground-truth.json and original image pairs were found.")

    manifest = [export_item(item, args.output, args.split) for item in items]
    write_metadata(args.output, manifest)
    total_annotations = sum(item["annotation_count"] for item in manifest)
    print(f"Exported {len(manifest)} images and {total_annotations} OBB labels to {args.output}")


if __name__ == "__main__":
    main()
