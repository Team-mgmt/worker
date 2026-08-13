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
