import json
from pathlib import Path

from PIL import Image

from worker.scripts.export_yolo_obb_dataset import ExportItem, export_item, write_metadata, yolo_obb_lines


def ground_truth() -> dict:
    return {
        "run_id": "run-1",
        "image": {"width": 200, "height": 100},
        "annotations": [
            {"polygon": [[20, 10], [80, 10], [80, 90], [20, 90]]},
            {"polygon": [[100, 0], [200, 0], [200, 100], [100, 100]]},
        ],
    }


def test_yolo_obb_lines_normalize_four_polygon_points() -> None:
    assert yolo_obb_lines(ground_truth(), 200, 100) == [
        "0 0.100000 0.100000 0.400000 0.100000 0.400000 0.900000 0.100000 0.900000",
        "0 0.500000 0.000000 1.000000 0.000000 1.000000 1.000000 0.500000 1.000000",
    ]


def test_export_item_writes_image_label_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    gt_path = source / "ground-truth.json"
    gt_path.write_text(json.dumps(ground_truth()), encoding="utf-8")
    image_path = source / "original.jpg"
    Image.new("RGB", (200, 100), "white").save(image_path)
    output = tmp_path / "dataset"

    manifest_item = export_item(ExportItem(gt_path, image_path), output, "train")
    write_metadata(output, [manifest_item])

    assert (output / "images/train/run-1.jpg").is_file()
    assert len((output / "labels/train/run-1.txt").read_text().splitlines()) == 2
    assert "0: book_spine" in (output / "data.yaml").read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"][0]["annotation_count"] == 2
