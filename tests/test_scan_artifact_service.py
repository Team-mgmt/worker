import json
from datetime import UTC, datetime

import pytest
from PIL import Image

from worker.schemas.inference import OCRResultItem, TargetBook
from worker.services.detection_service import BookSpineDetector
from worker.services.scan_artifact_service import ScanArtifactService, safe_key_part
from worker.services.target_matching_service import find_target_book


def test_safe_key_part_removes_s3_path_separators() -> None:
    assert safe_key_part(" 111189/../../test ") == "111189-..-..-test"


def test_build_prefix_is_partitioned_by_library_and_date(monkeypatch) -> None:
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.SCAN_ARTIFACTS_PREFIX", "shelfalign/scans/")
    service = ScanArtifactService()

    prefix = service.build_prefix("111189", "run-id", datetime(2026, 7, 12, tzinfo=UTC))

    assert prefix == "shelfalign/scans/111189/2026/07/12/run-id"


def test_storage_is_disabled_without_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.SCAN_ARTIFACTS_ENABLED", False)
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.S3_BUCKET_NAME", "real-bucket")

    assert ScanArtifactService().enabled is False


def test_detection_preserves_confidence_and_polygon() -> None:
    detection = BookSpineDetector._to_detection(
        [10.4, 20.8, 110.9, 220.2],
        [[12.0, 20.0], [111.0, 25.0], [108.0, 220.0], [10.0, 215.0]],
        0.91,
        is_obb=True,
    )

    assert detection.bbox == (10, 20, 100, 199)
    assert detection.confidence == 0.91
    assert detection.polygon[0] == [12.0, 20.0]
    assert detection.is_obb is True


@pytest.mark.asyncio
async def test_target_search_artifact_saves_full_scoring_diagnostics(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "shelf.jpg"
    Image.new("RGB", (200, 100), "white").save(image_path)
    ocr_results = [
        OCRResultItem(
            detected_order=1,
            raw_text="콩가루 수사단 주영하 813.6 주64ㅋ",
            title="콩가루 수사단",
            author="주영하",
            call_number="813.6 주64ㅋ",
            bbox=[10, 10, 90, 90],
            detection_confidence=0.95,
            obb_polygon=[[10, 10], [90, 10], [90, 90], [10, 90]],
        ),
        OCRResultItem(
            detected_order=2,
            raw_text="옆 책",
            title="옆 책",
            bbox=[100, 10, 190, 90],
            detection_confidence=0.90,
            obb_polygon=[[100, 10], [190, 10], [190, 90], [100, 90]],
        ),
    ]
    response = find_target_book(
        TargetBook(
            holding_id="holding-1",
            title="콩가루 수사단",
            author="주영하",
            call_number="813.6 주64ㅋ",
        ),
        ocr_results,
    )

    stored: dict[str, bytes] = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def put_object(self, *, Key, Body, **kwargs):
            stored[Key] = Body

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeClient()

    monkeypatch.setattr("worker.services.scan_artifact_service.aioboto3.Session", FakeSession)
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.SCAN_ARTIFACTS_ENABLED", True)
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr("worker.services.scan_artifact_service.settings.SCAN_ARTIFACTS_SAVE_CROPS", True)

    prefix = await ScanArtifactService().save_target_search(
        run_id="run-id",
        image_path=image_path,
        library_code="111058",
        response=response,
        ocr_results=ocr_results,
        timings={"detection": 0.1, "ocr": 2.2, "matching": 0.01},
        model_path=None,
        model_sha256="model-sha",
        vision_provider="modal",
    )

    assert prefix is not None
    payload = json.loads(stored[f"{prefix}/result.json"])
    assert payload["mode"] == "target_search"
    assert payload["target_search"]["target"]["holding_id"] == "holding-1"
    assert payload["target_search"]["detections"][0]["title_score"] == 100.0
    assert len(payload["inference"]["results"]) == 2
    assert payload["inference"]["results"][0]["crop_image_key"].endswith("/crops/001.jpg")
    assert payload["model"]["detector_sha256"] == "model-sha"
    assert f"{prefix}/original.jpg" in stored
    assert f"{prefix}/annotated.jpg" in stored
