from pathlib import Path

import pytest

from worker.services.remote_vision_service import FalVisionService, RemoteVisionError, RemoteVisionResponse


def test_remote_vision_response_rejects_missing_diagnostics() -> None:
    with pytest.raises(ValueError):
        RemoteVisionResponse.model_validate({"items": [], "detection_seconds": 1.0})


def test_remote_vision_response_preserves_obb_and_ocr_diagnostics() -> None:
    response = RemoteVisionResponse.model_validate(
        {
            "items": [
                {
                    "detected_order": 1,
                    "raw_text": "콩가루 수사단 813.6 주64ㅋ",
                    "bbox": [1.0, 2.0, 3.0, 4.0],
                    "obb_polygon": [[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0]],
                    "ocr_variant": "contact_sheet",
                    "ocr_attempt_count": 1,
                }
            ],
            "detection_seconds": 0.2,
            "ocr_seconds": 1.5,
            "model_sha256": "a" * 64,
        }
    )

    assert response.items[0].obb_polygon is not None
    assert response.items[0].ocr_variant == "contact_sheet"


@pytest.mark.asyncio
async def test_fal_service_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("worker.services.remote_vision_service.settings.FAL_VISION_ENDPOINT", "")
    with pytest.raises(RemoteVisionError, match="FAL_VISION_ENDPOINT"):
        await FalVisionService().analyze(Path("missing.jpg"), adaptive=False)
