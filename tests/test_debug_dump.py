"""Tests for the DebugDumper / DebugObserver / Cv2Tracer stack."""

from __future__ import annotations

import json
import os
import uuid

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from worker import paths
from worker.cv2_trace import Cv2Tracer
from worker.debug_dump import (
    ALLOW_DEBUG_ENV,
    ENABLE_DEBUG_ENV,
    DebugDumper,
    DebugObserver,
    build_observer,
    is_debug_active,
)
from worker.processor_observer import ProcessorObserver
from worker.types import ImageProcessingParams


@pytest.fixture
def storage_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "DEBUG_DIR", str(tmp_path / "debug"))
    return tmp_path


# ----- DebugDumper primitive -----


def test_disabled_dumper_writes_nothing(storage_tmp):
    request_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dumper = DebugDumper.from_params(request_id, job_id, ImageProcessingParams(debug=False))

    assert dumper.enabled is False
    dumper.save_image("scan.png", np.zeros((4, 4, 3), dtype=np.uint8))
    dumper.save_json("values.json", {"a": 1})

    debug_root = storage_tmp / "debug"
    assert not debug_root.exists() or not any(debug_root.iterdir())


def test_enabled_dumper_persists_image_and_json(storage_tmp):
    request_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dumper = DebugDumper.from_params(request_id, job_id, ImageProcessingParams(debug=True))

    assert dumper.enabled is True
    dumper.save_image("scan", np.zeros((2, 2), dtype=np.uint8))
    dumper.save_image("nested/inner.png", np.zeros((2, 2, 3), dtype=np.uint8))
    dumper.save_json("values", {"answer": 42, "uuid": request_id})

    job_dir = storage_tmp / "debug" / str(request_id) / str(job_id)
    assert (job_dir / "scan.png").exists()
    assert (job_dir / "nested" / "inner.png").exists()

    payload = json.loads((job_dir / "values.json").read_text(encoding="utf-8"))
    assert payload == {"answer": 42, "uuid": str(request_id)}


def test_dumper_rejects_paths_escaping_debug_dir(storage_tmp):
    dumper = DebugDumper.from_params(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=True))
    with pytest.raises(ValueError):
        dumper.save_image("../escape.png", np.zeros((2, 2), dtype=np.uint8))


def test_disabled_dumper_short_circuits_path_validation(storage_tmp):
    dumper = DebugDumper.from_params(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=False))
    dumper.save_image("../escape.png", np.zeros((2, 2), dtype=np.uint8))
    dumper.save_json("../escape.json", {})
    assert not os.path.exists(os.path.join(storage_tmp, "escape.png"))


# ----- build_observer factory -----


def test_build_observer_returns_noop_when_debug_off(storage_tmp, monkeypatch):
    monkeypatch.delenv(ALLOW_DEBUG_ENV, raising=False)
    monkeypatch.delenv(ENABLE_DEBUG_ENV, raising=False)
    obs = build_observer(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=False))
    assert type(obs) is ProcessorObserver
    # All methods callable on no-op without side-effects.
    obs.on_input_scan(np.zeros((2, 2), dtype=np.uint8))
    obs.on_aligned(np.zeros((2, 2), dtype=np.uint8), "noop", 0.0)
    obs.flush()


def test_build_observer_returns_debug_when_debug_on(storage_tmp, monkeypatch):
    monkeypatch.delenv(ALLOW_DEBUG_ENV, raising=False)
    monkeypatch.delenv(ENABLE_DEBUG_ENV, raising=False)
    obs = build_observer(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=True))
    assert isinstance(obs, DebugObserver)
    obs.flush()


# ----- is_debug_active env gating -----


@pytest.mark.parametrize(
    "allow,enable,params_debug,expected",
    [
        # Defaults: ALLOW=true (default), ENABLE=false (default) — falls back to params.
        (None, None, False, False),
        (None, None, True, True),
        # ALLOW kill switch wins over everything.
        ("false", "true", True, False),
        ("FALSE", None, True, False),
        ("0", None, True, False),
        # ENABLE force-on overrides params.debug=False (but still respects ALLOW).
        (None, "true", False, True),
        (None, "1", False, True),
        ("true", "yes", False, True),
        # Unknown ALLOW value treated as falsy (only recognized truthy strings count).
        ("maybe", None, True, False),
    ],
)
def test_is_debug_active_truth_table(monkeypatch, allow, enable, params_debug, expected):
    monkeypatch.delenv(ALLOW_DEBUG_ENV, raising=False)
    monkeypatch.delenv(ENABLE_DEBUG_ENV, raising=False)
    if allow is not None:
        monkeypatch.setenv(ALLOW_DEBUG_ENV, allow)
    if enable is not None:
        monkeypatch.setenv(ENABLE_DEBUG_ENV, enable)
    assert is_debug_active(ImageProcessingParams(debug=params_debug)) is expected


def test_build_observer_kill_switch_overrides_params(storage_tmp, monkeypatch):
    monkeypatch.setenv(ALLOW_DEBUG_ENV, "false")
    monkeypatch.setenv(ENABLE_DEBUG_ENV, "true")
    obs = build_observer(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=True))
    assert type(obs) is ProcessorObserver


def test_build_observer_force_enable_without_params(storage_tmp, monkeypatch):
    monkeypatch.setenv(ENABLE_DEBUG_ENV, "true")
    obs = build_observer(uuid.uuid4(), uuid.uuid4(), ImageProcessingParams(debug=False))
    assert isinstance(obs, DebugObserver)
    obs.flush()


# ----- Cv2Tracer end-to-end -----


def test_cv2_tracer_records_call_with_caller_source(storage_tmp, tmp_path):
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)
    img = np.zeros((4, 4, 3), dtype=np.uint8)

    with Cv2Tracer(dump_dir, save_images=True):
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)  # noqa: F841

    manifest = json.loads((tmp_path / "trace" / "cv2_calls.json").read_text(encoding="utf-8"))
    cvt_calls = [r for r in manifest if r["function"] == "cv2.cvtColor"]
    assert len(cvt_calls) == 1
    record = cvt_calls[0]
    assert record["caller"]["file"].endswith("test_debug_dump.py")
    assert "cv2.cvtColor" in record["caller"]["source"]
    assert record["args"][0] == {"_": "ndarray", "shape": [4, 4, 3], "dtype": "uint8"}
    assert record["result"] == {"_": "ndarray", "shape": [4, 4], "dtype": "uint8"}
    # 3-channel uint8 input → JPEG; 2-channel grayscale output → PNG.
    assert any("cv2_calls/" in p and "_in_0.jpg" in p for p in record["input_images"])
    assert any("cv2_calls/" in p and "_out.png" in p for p in record["output_images"])


def test_cv2_tracer_restores_originals(storage_tmp, tmp_path):
    original = cv2.cvtColor
    with Cv2Tracer(str(tmp_path / "trace"), save_images=False):
        assert cv2.cvtColor is not original
    assert cv2.cvtColor is original


def test_cv2_tracer_restores_originals_on_exception(storage_tmp, tmp_path):
    original = cv2.cvtColor
    with pytest.raises(RuntimeError):
        with Cv2Tracer(str(tmp_path / "trace"), save_images=False):
            assert cv2.cvtColor is not original
            raise RuntimeError("boom")
    assert cv2.cvtColor is original


def test_cv2_tracer_does_not_recurse_on_non_uint8_arrays(storage_tmp, tmp_path):
    """Regression for PR #63 Codex P1: _save_array must use the unpatched
    cv2.normalize so a traced call whose ndarray is float64 (e.g. a transform
    matrix) does not re-enter the tracer indefinitely.
    """
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)
    matrix = np.eye(3, dtype=np.float64)

    with Cv2Tracer(dump_dir, save_images=True):
        # Pass a float64 matrix as the first arg of a wrapped cv2 call. If
        # _save_array reached for the patched cv2.normalize, this would
        # recurse and blow the stack before returning.
        cv2.transpose(matrix)

    manifest = json.loads((tmp_path / "trace" / "cv2_calls.json").read_text(encoding="utf-8"))
    transposes = [r for r in manifest if r["function"] == "cv2.transpose"]
    assert len(transposes) == 1
    assert transposes[0]["args"][0] == {"_": "ndarray", "shape": [3, 3], "dtype": "float64"}


def test_cv2_tracer_dedups_repeated_input_array(storage_tmp, tmp_path):
    """Second call with the same ndarray reuses the first call's dump path.

    Same Python object passed as input to two cv2 calls → the second
    record's input_images points at the first record's encoded file
    (no new file written, no second encode). This is the main perf
    win for OMR-style pipelines where the warped image gets fed into
    dozens of downstream ops.
    """
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)
    img = np.zeros((4, 4, 3), dtype=np.uint8)

    with Cv2Tracer(dump_dir, save_images=True):
        cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    manifest = json.loads((tmp_path / "trace" / "cv2_calls.json").read_text(encoding="utf-8"))
    cvt_calls = [r for r in manifest if r["function"] == "cv2.cvtColor"]
    assert len(cvt_calls) == 2

    first_input = cvt_calls[0]["input_images"][0]
    second_input = cvt_calls[1]["input_images"][0]
    assert first_input == second_input, (
        "Same ndarray re-passed as input should reuse the first dump path; "
        f"got {first_input!r} vs {second_input!r}"
    )
    # Only one input file exists on disk for this id (the first call's).
    input_files = sorted((tmp_path / "trace" / "cv2_calls").glob("*_cvtColor_in_0.*"))
    assert len(input_files) == 1, [p.name for p in input_files]


def test_cv2_tracer_snapshots_outputs_before_async_encode(storage_tmp, tmp_path):
    """Output ndarrays must be copied before submit to the encoder pool.

    Regression for PR #66 Codex P2: ``_save_array`` used to pass output
    arrays by reference, so a downstream mutation (cv2 with ``dst=src``,
    in-place pipeline tweaks) could change the bytes between submit and
    encode and the dumped image would reflect a later state rather than
    the call-time result.
    """
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)

    arr = np.full((4, 4), 7, dtype=np.uint8)
    tracer = Cv2Tracer(dump_dir, save_images=True)
    with tracer:
        rel = tracer._save_array("cv2_calls/00001_output_snapshot", arr, is_input=False)
        assert rel is not None
        # Mutate the same buffer before the encoder pool drains.
        arr.fill(99)
    # PNG is lossless, so the encoded file must show the pre-mutation
    # value (7), not the post-mutation value (99).
    decoded = cv2.imread(str(tmp_path / "trace" / rel), cv2.IMREAD_GRAYSCALE)
    assert decoded is not None
    assert decoded.mean() == 7.0, f"encoded post-mutation bytes: mean={decoded.mean()}"


def test_cv2_tracer_scrubs_manifest_when_imwrite_returns_false(storage_tmp, tmp_path):
    """``cv2.imwrite`` returning False without raising must scrub manifest paths.

    Regression for PR #66 Codex P2: previously the manifest could
    reference nonexistent files (and the dedup cache could hand that
    bad path to later calls). ``_scrub_missing_paths`` in ``__exit__``
    drops any reference whose file isn't on disk once encoders drain.
    """
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)
    img = np.zeros((4, 4, 3), dtype=np.uint8)

    tracer = Cv2Tracer(dump_dir, save_images=True)
    # Force every imwrite to "silently fail" — the False-return failure
    # mode cv2 has for unwritable / unsupported targets.
    tracer._real_imwrite = lambda *args, **kwargs: False  # type: ignore[assignment]

    with tracer:
        cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    manifest = json.loads((tmp_path / "trace" / "cv2_calls.json").read_text(encoding="utf-8"))
    cvt = [r for r in manifest if r["function"] == "cv2.cvtColor"]
    assert len(cvt) == 1
    assert cvt[0]["input_images"] == []
    assert cvt[0]["output_images"] == []


def test_cv2_tracer_invalidates_dedup_on_in_place_mutation(storage_tmp, tmp_path):
    """When a cv2 call returns the same buffer it took as input (in-place
    mutation simulated via ``np.copyto`` running through a wrapped op),
    the cached entry for that id must be invalidated so the next
    observation re-encodes the (now-different) bytes.

    Implemented here with a wrapped no-op that returns its first arg —
    this is the same identity pattern that ``cv2.cvtColor(src, dst=src)``
    or in-place morphology produces, but built without needing a real
    in-place cv2 op so the test is fast and deterministic.
    """
    dump_dir = str(tmp_path / "trace")
    os.makedirs(dump_dir, exist_ok=True)

    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    tracer = Cv2Tracer(dump_dir, save_images=True)
    with tracer:
        # First observation as input via cvtColor — caches id(arr) → path_A.
        cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        # Force the same id(arr) through as an OUTPUT path. _save_array
        # with is_input=False pops the cache for this id, so the next
        # input observation must re-encode rather than reuse path_A.
        tracer._save_array("cv2_calls/99999_inplace_out", arr, is_input=False)

        # Now mutate the bytes so we can prove the re-encode happened
        # against the new state and not against the cached one.
        arr[:] = 200
        cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    manifest = json.loads((tmp_path / "trace" / "cv2_calls.json").read_text(encoding="utf-8"))
    cvt_calls = [r for r in manifest if r["function"] == "cv2.cvtColor"]
    assert len(cvt_calls) == 2
    first_input = cvt_calls[0]["input_images"][0]
    second_input = cvt_calls[1]["input_images"][0]
    assert first_input != second_input, (
        "Cache should have been invalidated by the output observation; "
        f"got duplicate input path {first_input!r}"
    )


# ----- DebugObserver end-to-end -----


def test_debug_observer_restores_cv2_when_flush_save_raises(storage_tmp):
    """Regression for PR #63 Codex P1: flush() must restore the global cv2
    monkey-patch even if writing bubble_decisions hits an OSError mid-flush
    (disk full, permission denied, etc.). Otherwise subsequent jobs would
    inherit a stranded tracer that nothing would ever __exit__.
    """
    request_id = uuid.uuid4()
    job_id = uuid.uuid4()
    obs = DebugObserver(request_id, job_id)
    original_cvtcolor = cv2.cvtColor.__wrapped__ if hasattr(cv2.cvtColor, "__wrapped__") else cv2.cvtColor

    obs.on_pipeline_start({}, ImageProcessingParams(debug=True))
    pre_flush_cvtcolor = cv2.cvtColor
    assert pre_flush_cvtcolor is not original_cvtcolor  # tracer is active

    # Force a non-empty bubble_decisions so the loop runs, then make
    # save_json raise on the first call.
    obs._bubble_decisions["identifier"] = [{"any": "decision"}]
    with patch.object(obs._dumper, "save_json", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            obs.flush()

    # cv2 must be restored despite the save failure.
    assert cv2.cvtColor is original_cvtcolor
    # Tracer reference cleared so a retry-flush is a no-op rather than
    # an AttributeError on a half-torn-down tracer.
    assert obs._cv2_tracer is None


def test_debug_observer_dumps_per_stage_artifacts(storage_tmp):
    request_id = uuid.uuid4()
    job_id = uuid.uuid4()
    params = ImageProcessingParams(debug=True)
    obs = DebugObserver(request_id, job_id)

    obs.on_pipeline_start({"recognition_max_width": 1000}, params)
    try:
        # During a debug pipeline, ANY cv2 call between on_pipeline_start and
        # flush() is captured by the global monkey-patch.
        gray = cv2.cvtColor(np.zeros((4, 4, 3), dtype=np.uint8), cv2.COLOR_RGB2GRAY)
        obs.on_input_scan(np.zeros((2, 2, 3), dtype=np.uint8))
        obs.on_aligned(np.zeros((4, 4, 3), dtype=np.uint8), "romav2_dense", 0.91)
        obs.on_binarized(gray, gray)
    finally:
        obs.flush()

    job_dir = storage_tmp / "debug" / str(request_id) / str(job_id)
    assert (job_dir / "params.json").exists()
    assert (job_dir / "00_input_scan.png").exists()
    assert (job_dir / "05_warped.png").exists()
    assert (job_dir / "06_warped_thresh.png").exists()
    assert (job_dir / "alignment.json").exists()
    assert (job_dir / "cv2_calls.json").exists()

    calls = json.loads((job_dir / "cv2_calls.json").read_text(encoding="utf-8"))
    # The explicit cv2.cvtColor in this test goes through the patched
    # module, so it's traced. The observer's own save_image()/cvtColor()
    # calls use refs captured by DebugDumper.__init__ before patching,
    # so they intentionally do NOT appear under cv2_calls/.
    assert any(r["function"] == "cv2.cvtColor" for r in calls)
    assert not any(r["function"] == "cv2.imwrite" for r in calls)
