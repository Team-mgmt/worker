from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from worker.core.database import AsyncSessionLocal
from worker.schemas.inference import OCRResultItem, ScanSessionRequest
from worker.services.inference_service import process_scan_session_request


NOWON_JUNGANG_LIBRARY_CODE = "111058"
DEFAULT_BBOXES_JSON = Path("worker/tests/bboxes.json")
DEFAULT_OUTPUT_DIR = Path("outputs/nowon_scan")
STATUS_COLORS = {
    "normal": (40, 180, 70),
    "suspected_misplacement": (40, 40, 230),
    "needs_review": (20, 190, 230),
    "unmatched": (130, 130, 130),
}


def read_image(image_path: Path) -> np.ndarray:
    image_array = np.fromfile(str(image_path), np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Failed to read image: {image_path}")
    return image


def load_manual_boxes(bboxes_json: Path, image_path: Path, image_key: str | None) -> list[dict[str, Any]]:
    with bboxes_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    candidates = [image_key, image_path.name, str(image_path)] if image_key else [image_path.name, str(image_path)]
    for key in candidates:
        if key and key in data:
            return data[key]

    available = ", ".join(data.keys())
    raise KeyError(f"No BBox entry for {image_path.name}. Available keys: {available}")


def detect_boxes(image_path: Path, mode: str, bboxes_json: Path, image_key: str | None) -> list[dict[str, Any]]:
    if mode == "manual":
        return load_manual_boxes(bboxes_json, image_path, image_key)

    from worker.services.detection_service import detector_service

    boxes = detector_service.detect_spines(str(image_path))
    return [{"bbox": [x, y, w, h]} for x, y, w, h in boxes]


def draw_results(image: np.ndarray, results: list[dict[str, Any]], output_path: Path) -> None:
    for result in results:
        bbox = result.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox]
        status = result.get("decision", "unmatched")
        color = STATUS_COLORS.get(status, (255, 255, 255))
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)

        label = result.get("matched_call_number") or result.get("ocr_call_number") or status
        cv2.putText(image, str(label)[:32], (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(output_path.suffix or ".png", image)
    if not ok:
        raise RuntimeError(f"Failed to encode output image: {output_path}")
    encoded.tofile(str(output_path))


async def run_scan(args: argparse.Namespace) -> None:
    image_path = Path(args.image)
    output_dir = Path(args.output_dir)
    image = read_image(image_path)
    boxes = detect_boxes(image_path, args.mode, Path(args.bboxes_json), args.image_key)

    from worker.services.vision_service import vision_service

    ocr_results = []
    for index, box_info in enumerate(boxes, start=1):
        x, y, w, h = [int(v) for v in box_info["bbox"]]
        try:
            extracted = vision_service.manual_crop_and_ocr(str(image_path), (x, y, w, h), preprocess=args.preprocess)
            text = " ".join(item["text"] for item in extracted)
            confidence = sum(item["confidence"] for item in extracted) / len(extracted) if extracted else 0.0
        except Exception as exc:
            print(f"OCR failed for box {index}: {exc}")
            text = ""
            confidence = 0.0

        print(f"{index:02d}. OCR='{text}' confidence={confidence:.3f}")
        ocr_results.append(
            OCRResultItem(
                detected_order=index,
                raw_text=text,
                call_number=text,
                bbox=[x, y, x + w, y + h],
                ocr_confidence=confidence,
            )
        )

    request = ScanSessionRequest(
        library_code=args.lib_code,
        room_name=args.room_name,
        source_name=image_path.name,
        expected_shelf_start=args.expected_shelf_start,
        expected_shelf_end=args.expected_shelf_end,
        ocr_results=ocr_results,
    )

    async with AsyncSessionLocal() as session:
        response = await process_scan_session_request(request, db=session)

    result_data = response.model_dump(mode="json")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{image_path.stem}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    overlay_path = output_dir / f"{image_path.stem}_overlay.png"
    draw_results(image, result_data["results"], overlay_path)

    print(f"Saved JSON: {json_path}")
    print(f"Saved overlay: {overlay_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Nowon Jungang shelf scan against the Data4Library-backed catalog.")
    parser.add_argument("image", help="Shelf image path.")
    parser.add_argument("--lib-code", default=NOWON_JUNGANG_LIBRARY_CODE)
    parser.add_argument("--room-name", default="Nowon Jungang Library")
    parser.add_argument("--mode", choices=["manual", "yolo"], default="manual")
    parser.add_argument("--bboxes-json", default=str(DEFAULT_BBOXES_JSON))
    parser.add_argument("--image-key", default=None, help="Key inside the BBox JSON. Defaults to the image filename.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--expected-shelf-start", type=float, default=None)
    parser.add_argument("--expected-shelf-end", type=float, default=None)
    parser.add_argument("--preprocess", action="store_true", help="Run label-focused preprocessing before OCR.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_scan(args))


if __name__ == "__main__":
    main()
