from __future__ import annotations

import numpy as np

from worker.services.vision_service import VisionService


def ocr_item(text: str, confidence: float) -> dict:
    return {"text": text, "confidence": confidence, "bbox": []}


def test_candidate_score_prioritizes_call_number_evidence() -> None:
    title_only = [ocr_item("clear book title", 0.99)]
    with_call_number = [ocr_item("blurred title 813.6 ABC211M", 0.72)]

    assert VisionService._candidate_score(with_call_number) > VisionService._candidate_score(title_only)


def test_call_number_detection_rejects_plain_title_number() -> None:
    assert VisionService._has_call_number("Mint World 813.6 ABC211M")
    assert not VisionService._has_call_number("Youth Literature 53")


def test_label_region_uses_configured_bottom_area_and_upscales() -> None:
    image = np.zeros((1000, 100, 3), dtype=np.uint8)

    label = VisionService._prepare_label_region(image)

    assert label.shape[0] == 896
    assert label.shape[1] == 256
