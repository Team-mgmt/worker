from datetime import UTC, datetime

from worker.services.scan_artifact_service import ScanArtifactService, safe_key_part
from worker.services.detection_service import BookSpineDetector


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
