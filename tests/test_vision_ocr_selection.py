from __future__ import annotations

import numpy as np
import pytest

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


def test_adaptive_ocr_uses_one_pass_when_primary_has_call_number(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService.__new__(VisionService)
    calls = 0

    def run_ocr(_image: np.ndarray) -> list[dict]:
        nonlocal calls
        calls += 1
        return [ocr_item("콩가루 수사단 813.6 주64ㅋ", 0.95)]

    monkeypatch.setattr(service, "_run_ocr", run_ocr)
    extracted, diagnostics = service._adaptive_ocr(np.zeros((100, 30, 3), dtype=np.uint8))

    assert calls == 1
    assert diagnostics["attempt_count"] == 1
    assert diagnostics["variant"] == "original"
    assert extracted[0]["text"].startswith("콩가루")


def test_fast_ocr_never_runs_label_or_fallback_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService.__new__(VisionService)
    calls = 0

    def run_ocr(_image: np.ndarray) -> list[dict]:
        nonlocal calls
        calls += 1
        return [ocr_item("콩가루 수사단", 0.5)]

    monkeypatch.setattr(service, "_run_ocr", run_ocr)
    _, diagnostics = service._adaptive_ocr(
        np.zeros((100, 30, 3), dtype=np.uint8),
        adaptive=False,
    )

    assert calls == 1
    assert diagnostics["attempt_count"] == 1
    assert diagnostics["label_text"] is None


def test_contact_sheet_distributes_text_back_to_each_spine() -> None:
    crops = [
        np.zeros((20, 10, 3), dtype=np.uint8),
        np.zeros((20, 12, 3), dtype=np.uint8),
    ]
    sheet, ranges = VisionService._compose_contact_sheet(crops)
    first_center = (ranges[0][0] + ranges[0][1]) / 2
    second_center = (ranges[1][0] + ranges[1][1]) / 2
    extracted = [
        {"text": "첫 책", "confidence": 0.9, "bbox": [[first_center - 1, 0], [first_center + 1, 0]]},
        {"text": "둘째 책", "confidence": 0.8, "bbox": [[second_center - 1, 0], [second_center + 1, 0]]},
    ]

    grouped = VisionService._distribute_contact_sheet_results(extracted, ranges)

    assert sheet.shape[1] == 10 + 12 + 24
    assert [item[0]["text"] for item in grouped] == ["첫 책", "둘째 책"]
    assert grouped[1][0]["bbox"][0][0] < 12


def test_fast_batch_decodes_source_once_and_uses_one_ocr_call(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService.__new__(VisionService)
    service.ocr = object()
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    loads = 0
    calls = 0

    def load_image(_path: str) -> np.ndarray:
        nonlocal loads
        loads += 1
        return image

    def run_ocr(_sheet: np.ndarray) -> list[dict]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(service, "_load_image", load_image)
    monkeypatch.setattr(service, "_run_ocr", run_ocr)
    results, metadata = service.crop_many_for_fast_ocr(
        "unused.jpg",
        [((0, 0, 10, 20), None), ((10, 0, 10, 20), None)],
    )

    assert loads == 1
    assert calls == 1
    assert results == [[], []]
    assert [item.ocr_variant for item in metadata] == ["contact_sheet", "contact_sheet"]
