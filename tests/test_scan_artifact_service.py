from datetime import UTC, datetime

from worker.services.scan_artifact_service import ScanArtifactService, safe_key_part


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
