from pathlib import Path

import pytest

from worker.services.remote_vision_service import RemoteVisionError, RemoteVisionResponse, RemoteVisionService


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
async def test_remote_service_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("worker.services.remote_vision_service.settings.REMOTE_VISION_ENDPOINT", "")
    with pytest.raises(RemoteVisionError, match="REMOTE_VISION_ENDPOINT"):
        await RemoteVisionService().analyze(Path("missing.jpg"), adaptive=False)


@pytest.mark.asyncio
async def test_remote_service_posts_image_and_parses_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "shelf.jpg"
    image_path.write_bytes(b"image-bytes")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.REMOTE_VISION_ENDPOINT", "https://example.modal.run")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.MODAL_TOKEN_ID", "wk-test")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.MODAL_TOKEN_SECRET", "ws-test")
    monkeypatch.setattr(
        RemoteVisionService,
        "_post_json",
        staticmethod(
            lambda endpoint, payload: {
                "items": [{"detected_order": 1, "raw_text": "환한 숨", "bbox": [1, 2, 3, 4]}],
                "detection_seconds": 0.1,
                "ocr_seconds": 0.5,
                "model_sha256": "b" * 64,
            }
        ),
    )

    items, detection_seconds, ocr_seconds, model_sha256 = await RemoteVisionService().analyze(
        image_path,
        adaptive=False,
    )

    assert items[0].raw_text == "환한 숨"
    assert detection_seconds == 0.1
    assert ocr_seconds == 0.5
    assert model_sha256 == "b" * 64
