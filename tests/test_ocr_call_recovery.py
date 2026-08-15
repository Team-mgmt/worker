from pathlib import Path

import pytest

from worker.services.ocr_field_parser import extract_ocr_fields
from worker.services.remote_vision_service import RemoteVisionService

RAW_FIRST_SNOW = (
    "\uc0ac\uacc4\uacb0 1318 \ubb38\uace0 102 \uccad\ub208\uc774 \ub0b4R \uc9c4 \ud76c \uc7a5\ud3b8\uc18c\uc124 "
    "\ub178\uc6d0\uc815\ubcf4 \ubb38\ud559 813.6 98\u314a 800"
)


def test_recovers_book_code_missing_leading_hangul_from_raw_text() -> None:
    title, author, call_number = extract_ocr_fields(RAW_FIRST_SNOW)

    assert title == "\uc0ac\uacc4\uacb0 1318 \ubb38\uace0 102 \uccad\ub208\uc774 \ub0b4R"
    assert author == "\uc9c4\ud76c"
    assert call_number == "813.6 98\u314a"


@pytest.mark.asyncio
async def test_remote_service_recovers_call_number_from_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "shelf.jpg"
    image_path.write_bytes(b"image-bytes")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.REMOTE_VISION_ENDPOINT", "https://example.modal.run")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.MODAL_TOKEN_ID", "wk-test")
    monkeypatch.setattr("worker.services.remote_vision_service.settings.MODAL_TOKEN_SECRET", "ws-test")

    def fake_post(endpoint, payload):
        return {
            "items": [{"detected_order": 35, "raw_text": RAW_FIRST_SNOW, "bbox": [1, 2, 3, 4]}],
            "detection_seconds": 0.1,
            "ocr_seconds": 0.5,
            "model_sha256": "c" * 64,
        }

    monkeypatch.setattr(RemoteVisionService, "_post_json", staticmethod(fake_post))

    items, *_ = await RemoteVisionService().analyze(image_path, adaptive=True)

    assert items[0].call_number == "813.6 98\u314a"
    assert items[0].author == "\uc9c4\ud76c"
    assert items[0].title == "\uc0ac\uacc4\uacb0 1318 \ubb38\uace0 102 \uccad\ub208\uc774 \ub0b4R"
