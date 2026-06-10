"""Offline smoke test against a captured dev scan request.

Replays the post-alignment half of ``ProcessorV1.process`` against a real
scan request without S3, the database, or the RoMaV2 GPU aligner. The
fixture under ``tests/fixtures/smoke/<request-id>/`` carries:

  - ``scan.jpg``      — the original scan (needed for QR decoding)
  - ``template.svg``  — the exam paper background
  - ``warped.png``    — the post-RoMaV2 warped scan from the captured run
  - ``area_metrics.json`` — golden per-bubble metrics for assertions
  - ``fixture.json``  — the DB rows ProcessorV1 reads (Exam, ExamPaper,
    areas, area types) plus job metadata and ScanLogs

The test patches three seams to keep the run hermetic:

  - ``prepare_image``         → reads local fixture files
  - ``_get_database_records`` → returns objects built from ``fixture.json``
  - ``_align_scan_to_template`` → returns the pre-captured ``warped.png``

Everything between QR decoding and the final scoring still runs for real
— template rasterization, recognition resize, QR-on-template render,
post-warp binarization, area detection, and bubble fill detection.

Refresh with::

    AWS_PROFILE=shelfalign uv run python scripts/extract_smoke_fixture.py <scan-id>
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import cv2
import numpy as np
import pytest

from worker.generated.models import Exampaperareabasetype
from worker.processors.v1 import ProcessorV1


SMOKE_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "smoke"


def _available_fixtures() -> list[Path]:
    if not SMOKE_FIXTURES_DIR.exists():
        return []
    return [
        p for p in SMOKE_FIXTURES_DIR.iterdir()
        if p.is_dir() and (p / "fixture.json").exists() and (p / "warped.png").exists()
    ]


def _build_area_type(at_row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(at_row["id"]),
        name=at_row["name"],
        base_type=Exampaperareabasetype(at_row["baseType"]),
        choice_type_id=at_row.get("choiceTypeId") and UUID(at_row["choiceTypeId"]),
        choice_type=None,
        data=at_row.get("data") or {},
    )


def _build_area(area_row: dict, area_type: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(area_row["id"]),
        exam_paper_id=UUID(area_row["examPaperId"]),
        pos_x=float(area_row["posX"]),
        pos_y=float(area_row["posY"]),
        width=float(area_row["width"]),
        height=float(area_row["height"]),
        data=area_row["data"],
        area_type_id=UUID(area_row["areaTypeId"]),
        index=int(area_row["index"]),
        area_type=area_type,
    )


def _build_orm_objects(fixture: dict):
    import datetime as _dt

    exam_round = SimpleNamespace(
        id=UUID(fixture["exam_round"]["id"]),
        exam_id=UUID(fixture["exam_round"]["examId"]),
        name=fixture["exam_round"].get("name", ""),
        updated_at=_dt.datetime(2026, 1, 1),
    )
    exam = SimpleNamespace(
        id=UUID(fixture["exam"]["id"]),
        organization_id=UUID(fixture["exam"]["organizationId"]),
        exam_paper_id=UUID(fixture["exam"]["examPaperId"]),
        title=fixture["exam"].get("title", ""),
        year=fixture["exam"].get("year", ""),
        round_number=fixture["exam"].get("roundNumber"),
        updated_at=_dt.datetime(2026, 1, 2),
    )
    exam_paper = SimpleNamespace(
        id=UUID(fixture["exam_paper"]["id"]),
        background_image=fixture["exam_paper"]["backgroundImage"],
        paper_type_id=UUID(fixture["exam_paper"]["paperTypeId"]),
        updated_at=_dt.datetime(2026, 1, 3),
    )
    paper_type = SimpleNamespace(id=UUID(fixture["paper_type"]["id"]))
    area_types_by_id = {at["id"]: _build_area_type(at) for at in fixture["area_types"]}
    areas = [_build_area(a, area_types_by_id[a["areaTypeId"]]) for a in fixture["areas"]]
    primary_area = next(a for a in areas if str(a.id) == fixture["qr"]["area_id"])
    return exam_round, exam, exam_paper, paper_type, primary_area, areas


def _load_image_rgb(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path))
    if bgr is None:
        raise RuntimeError(f"Failed to load image at {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _build_expected_answers(
    fixture: dict, area_metrics: dict[str, dict],
) -> dict[str, dict[int, list[str]]]:
    """Project per-bubble is_filled into the (area.index → [local_id]) shape
    produced by ProcessorV1.

    This is the same level the worker stores as ExamSubmission / DraftSubmission
    answers, so the test asserts what the student *answered* — not the
    numerical fill ratio, which drifts with binarization/detection tweaks.

    Returned dict has three keys mirroring ProcessResult: ``student_info``,
    ``problem``, ``option``. QRCODE areas are ignored — they're handled by
    QR detection, not bubble fill.
    """
    base_type_to_bucket = {
        "IDENTIFIER": "student_info",
        "PROBLEM": "problem",
        "OPTION": "option",
    }
    area_types_by_id = {at["id"]: at for at in fixture["area_types"]}
    areas_by_id = {a["id"]: a for a in fixture["areas"]}

    expected: dict[str, dict[int, list[str]]] = {"student_info": {}, "problem": {}, "option": {}}
    # Seed every area's index so empty answers ([]) compare correctly.
    for area in fixture["areas"]:
        at = area_types_by_id[area["areaTypeId"]]
        bucket = base_type_to_bucket.get(at["baseType"])
        if bucket is not None:
            expected[bucket][int(area["index"])] = []

    for bubble_key, metrics in area_metrics.items():
        if not metrics["is_filled"]:
            continue
        area_id, _, local_id = bubble_key.partition("_")
        area = areas_by_id.get(area_id)
        if area is None:
            continue
        at = area_types_by_id[area["areaTypeId"]]
        bucket = base_type_to_bucket.get(at["baseType"])
        if bucket is not None:
            expected[bucket][int(area["index"])].append(local_id)

    for bucket in expected.values():
        for ids in bucket.values():
            ids.sort()
    return expected


async def _fake_prepare_image(
    fixture_dir: Path,
    _client,
    _bucket,
    _image_id,
    _image_key,
    image_type,
    **kwargs,
):
    """Load template/scan from the captured fixture instead of S3."""
    fixture_json = json.loads((fixture_dir / "fixture.json").read_text())
    rel = fixture_json["image_files"]["template" if image_type == "templates" else "scan"]
    path = fixture_dir / rel

    if path.suffix.lower() == ".svg":
        # Rasterize via the real helper so coordinate scaling matches production.
        import cairosvg

        from worker.util import _resolve_svg_render_dims  # type: ignore[attr-defined]

        svg_bytes = path.read_bytes()
        svg_min_render_width = kwargs.get("svg_min_render_width") or 2400
        out_w, out_h, scale = _resolve_svg_render_dims(svg_bytes, svg_min_render_width)
        png_bytes = cairosvg.svg2png(
            bytestring=svg_bytes, output_width=out_w, output_height=out_h, background_color="white",
        )
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        rgb = cv2.cvtColor(cv2.imdecode(arr, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        return rgb, scale

    return _load_image_rgb(path), 1.0


@pytest.mark.smoke
@pytest.mark.parametrize("fixture_dir", _available_fixtures(), ids=lambda p: p.name)
async def test_smoke_scan_request_processes(tmp_path, fixture_dir, monkeypatch):
    """Replay one scan end-to-end against a captured fixture.

    Skipped automatically when no fixture is checked in (parametrize
    generates zero cases).
    """
    monkeypatch.setenv("WORKER_STORAGE_DIR", str(tmp_path))
    import importlib

    from worker import paths as paths_module

    importlib.reload(paths_module)
    paths_module.init_storage_dirs()

    fixture = json.loads((fixture_dir / "fixture.json").read_text())
    scan_rgb = _load_image_rgb(fixture_dir / fixture["image_files"]["scan"])
    warped_rgb = _load_image_rgb(fixture_dir / fixture["image_files"]["warped"])
    golden_metrics = json.loads(
        (fixture_dir / fixture["result_files"]["area_metrics"]).read_text()
    )
    expected_answers = _build_expected_answers(fixture, golden_metrics)

    orm_records = _build_orm_objects(fixture)

    processor = ProcessorV1.__new__(ProcessorV1)
    processor.client = AsyncMock()
    processor.bucket_name = "smoke-test"
    processor.engine = MagicMock()
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    session_cm.__aexit__ = AsyncMock(return_value=None)
    processor.session_factory = MagicMock(return_value=session_cm)
    processor._logger = AsyncMock()
    processor._profiler = None
    # No matcher needed — _align_scan_to_template is patched out.
    processor._matcher = MagicMock()

    async def _fake_prepare(*args, **kwargs):
        return await _fake_prepare_image(fixture_dir, *args, **kwargs)

    async def _fake_align(_self, _scan, _template):
        return warped_rgb, "smoke_replay", 1.0

    # TEXT-area rendering hits S3 for fonts; the smoke fixture isn't a font
    # source, so stub it out. The golden metrics were captured against a
    # template without rendered TEXT, so this keeps the comparison apples-to-
    # apples.
    async def _fake_text_render(**_kwargs):
        return 0

    with (
        patch("worker.processors.v1.prepare_image", side_effect=_fake_prepare),
        patch("worker.processors.v1.render_text_areas_on_template", side_effect=_fake_text_render),
        patch.object(ProcessorV1, "_get_database_records", AsyncMock(return_value=orm_records)),
        patch.object(ProcessorV1, "_align_scan_to_template", _fake_align),
    ):
        result = await processor.process(
            scan_rgb,
            job_id=UUID("00000000-0000-0000-0000-000000000001"),
            request_id=UUID(fixture["scan_request"]["id"]),
            metadata=fixture["scan_request"]["metadata"],
        )

    # Structural assertions.
    assert result["organization_id"] == orm_records[1].organization_id
    assert result["exam_id"] == orm_records[1].id
    assert result["exam_round_id"] == orm_records[0].id
    assert Path(result["image_threshold_path"]).exists()
    assert Path(result["image_flattened_path"]).exists()
    assert Path(result["image_annotated_cropped_path"]).exists()

    # Answer-level golden comparison. Per-bubble fill_ratio shifts on any
    # binarization/detection tweak, so asserting it would make this test a
    # change-detector. Asserting the resolved answers (which choices the
    # student picked per area) is the same level the worker writes to
    # ExamSubmission / DraftSubmission — algorithm refactors that preserve
    # accuracy stay green; regressions that flip an answer fail.
    def _normalize(detected: dict[int, list[str]]) -> dict[int, list[str]]:
        return {int(idx): sorted(ids) for idx, ids in detected.items()}

    actual_answers = {
        "student_info": _normalize(result["student_info_results"]),
        "problem": _normalize(result["problem_results"]),
        "option": _normalize(result["option_results"]),
    }
    for bucket in ("student_info", "problem", "option"):
        assert actual_answers[bucket] == expected_answers[bucket], (
            f"{bucket} answers diverged from captured golden\n"
            f"  expected: {expected_answers[bucket]}\n"
            f"  actual:   {actual_answers[bucket]}"
        )
