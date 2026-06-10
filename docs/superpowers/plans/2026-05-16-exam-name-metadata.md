# EXAM_NAME Metadata Name-History + Force-Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a metadata area's `area_type.name == "EXAM_NAME"`, seed `currentNameEditId` + `nameHistory` into submission metadata, and force a draft (non-teacher scans only) when the exam name can't be resolved.

**Architecture:** All changes are in `worker/worker/scan.py` plus constants in `worker/consts.py`. `_derive_metadata_payload` injects the name-history keys directly into the existing `payload` dict. The "unresolved" signal is **derived** from the payload (`"nameHistory" not in payload` + an EXAM_NAME area exists) via a small pure helper, rather than changing the method's return type. This is a deliberate refinement of the approved spec: observable behaviour is identical, but it avoids churning the 7 existing `_derive_metadata_payload` tests and the two `metadata_=` call sites.

**Tech Stack:** Python 3, pytest (`uv run -m pytest`), ruff, mypy.

---

## File Structure

- `worker/consts.py` — add three module-level string constants (existing constants file; pattern: plain module-level literals).
- `worker/worker/scan.py` — add an ISO-8601 UTC helper, two small pure decision helpers on `ScanWorker`, modify `_derive_metadata_payload`, and modify the draft/direct branch (~line 777).
- `tests/test_scan_worker.py` — extend `TestDeriveMetadataPayload`, add focused unit tests for the new helpers.

---

## Task 1: Constants + ISO-8601 UTC timestamp helper

**Files:**
- Modify: `worker/consts.py`
- Modify: `worker/worker/scan.py` (imports + new module-level helper)
- Test: `tests/test_scan_worker.py`

- [ ] **Step 1: Add constants to `worker/consts.py`**

Append to the end of `worker/consts.py` (after line 10):

```python

# Metadata area whose stringified value is the exam taker's name. Matched
# against ExamPaperAreaType.name verbatim.
EXAM_NAME_AREA_TYPE = "EXAM_NAME"

# Sentinel "nil" UUID written into worker-seeded name-history entries.
NIL_UUID = "00000000-0000-0000-0000-000000000000"

# `source` literal for worker-authored nameHistory entries. NOT a Scansource
# DB enum value (that enum is STUDENT/TEACHER only); this only ever lives in
# the submission.metadata JSONB.
NAME_HISTORY_SOURCE_WORKER = "WORKER"
```

- [ ] **Step 2: Write the failing test for the timestamp helper**

Add to `tests/test_scan_worker.py` (new test class, place it directly above `class TestDeriveMetadataPayload:`):

```python
class TestIso8601UtcNow:
    def test_format_is_iso8601_utc_millis_z(self):
        import re

        from worker.worker.scan import _iso8601_utc_now

        value = _iso8601_utc_now()
        # e.g. 2026-05-16T12:34:56.789Z
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value
        ), value
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run -m pytest tests/test_scan_worker.py::TestIso8601UtcNow -v`
Expected: FAIL with `ImportError: cannot import name '_iso8601_utc_now'`

- [ ] **Step 4: Implement the helper**

In `worker/worker/scan.py`, change the datetime import on line 9 from:

```python
from datetime import datetime
```

to:

```python
from datetime import datetime, timezone
```

Then add this module-level function immediately after the imports block (after line 40, before the first class/definition in the file):

```python
def _iso8601_utc_now() -> str:
    """Current UTC time as an ISO-8601 string, millisecond precision, 'Z' suffix.

    Independent of the naive ``datetime.now()`` used for DB columns elsewhere in
    this module — this value is embedded in submission.metadata JSON and must be
    an explicit UTC instant (e.g. ``2026-05-16T12:34:56.789Z``).
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run -m pytest tests/test_scan_worker.py::TestIso8601UtcNow -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add worker/consts.py worker/worker/scan.py tests/test_scan_worker.py
git commit -m "feat: add EXAM_NAME constants and ISO-8601 UTC helper"
```

---

## Task 2: `_is_exam_name_unresolved` decision helper

This pure helper derives the unresolved signal from the already-built payload, so the branch logic and `_derive_metadata_payload` stay decoupled.

**Files:**
- Modify: `worker/worker/scan.py`
- Test: `tests/test_scan_worker.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scan_worker.py` (new test class, below `TestDeriveMetadataPayload`):

```python
class TestIsExamNameUnresolved:
    def _area(self, type_name):
        area = MagicMock()
        area.area_type = MagicMock()
        area.area_type.name = type_name
        return area

    def test_false_when_no_exam_name_area(self, mock_scan_worker):
        areas = [self._area("ROOM"), self._area("CLASS")]
        assert mock_scan_worker._is_exam_name_unresolved(areas, {"x": "y"}) is False

    def test_false_when_exam_name_resolved(self, mock_scan_worker):
        areas = [self._area("EXAM_NAME")]
        payload = {"nameHistory": [{"name": "Jane"}]}
        assert mock_scan_worker._is_exam_name_unresolved(areas, payload) is False

    def test_true_when_exam_name_area_but_no_name_history(self, mock_scan_worker):
        areas = [self._area("EXAM_NAME"), self._area("ROOM")]
        assert mock_scan_worker._is_exam_name_unresolved(areas, {}) is True

    def test_handles_area_with_no_area_type(self, mock_scan_worker):
        bad = MagicMock()
        bad.area_type = None
        assert mock_scan_worker._is_exam_name_unresolved([bad], {}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run -m pytest tests/test_scan_worker.py::TestIsExamNameUnresolved -v`
Expected: FAIL with `AttributeError: ... has no attribute '_is_exam_name_unresolved'`

- [ ] **Step 3: Implement the helper**

In `worker/worker/scan.py`, add this method to the `ScanWorker` class, directly above `_derive_metadata_payload` (above line 150). Add the import for the constant at the top with the other `..consts` import (line 23 currently `from ..consts import JOB_MAX_RETRIES, JOB_TIMEOUT_MINUTES`) — change it to:

```python
from ..consts import (
    EXAM_NAME_AREA_TYPE,
    JOB_MAX_RETRIES,
    JOB_TIMEOUT_MINUTES,
    NAME_HISTORY_SOURCE_WORKER,
    NIL_UUID,
)
```

Method:

```python
    def _is_exam_name_unresolved(
        self,
        metadata_areas: list[ExamPaperArea],
        metadata_payload: dict[str, Any],
    ) -> bool:
        """True iff an EXAM_NAME metadata area exists but no resolved name was
        injected into the payload.

        ``_derive_metadata_payload`` only writes the ``nameHistory`` key when an
        EXAM_NAME area stringifies to a non-empty value, so its absence (given an
        EXAM_NAME area is present) means the name could not be resolved.
        """
        has_exam_name_area = any(
            a.area_type is not None and a.area_type.name == EXAM_NAME_AREA_TYPE
            for a in metadata_areas
        )
        return has_exam_name_area and "nameHistory" not in metadata_payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run -m pytest tests/test_scan_worker.py::TestIsExamNameUnresolved -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add worker/worker/scan.py tests/test_scan_worker.py
git commit -m "feat: add _is_exam_name_unresolved helper"
```

---

## Task 3: `_force_draft_for_unresolved_name` decision helper

**Files:**
- Modify: `worker/worker/scan.py`
- Test: `tests/test_scan_worker.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scan_worker.py` (below `TestIsExamNameUnresolved`):

```python
class TestForceDraftForUnresolvedName:
    def test_true_when_unresolved_and_not_teacher(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(True, "STUDENT") is True

    def test_false_when_unresolved_but_teacher(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(True, "TEACHER") is False

    def test_false_when_resolved(self, mock_scan_worker):
        assert mock_scan_worker._force_draft_for_unresolved_name(False, "STUDENT") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run -m pytest tests/test_scan_worker.py::TestForceDraftForUnresolvedName -v`
Expected: FAIL with `AttributeError: ... has no attribute '_force_draft_for_unresolved_name'`

- [ ] **Step 3: Implement the helper**

In `worker/worker/scan.py`, add this method to `ScanWorker` directly below `_is_exam_name_unresolved`:

```python
    def _force_draft_for_unresolved_name(
        self,
        exam_name_unresolved: bool,
        scan_request_source: str,
    ) -> bool:
        """Force a DraftSubmission when the exam name is unresolved — except for
        TEACHER scans, which always go to a direct ExamSubmission."""
        return exam_name_unresolved and scan_request_source != "TEACHER"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run -m pytest tests/test_scan_worker.py::TestForceDraftForUnresolvedName -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add worker/worker/scan.py tests/test_scan_worker.py
git commit -m "feat: add _force_draft_for_unresolved_name helper"
```

---

## Task 4: Inject name-history keys in `_derive_metadata_payload`

**Files:**
- Modify: `worker/worker/scan.py:150-223` (`_derive_metadata_payload`)
- Test: `tests/test_scan_worker.py` (`TestDeriveMetadataPayload`)

- [ ] **Step 1: Write the failing tests**

Add these methods inside the existing `class TestDeriveMetadataPayload:` (after `test_unknown_area_id_skips`):

```python
    async def test_exam_name_area_injects_name_history(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="Jane Doe")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]}, [area]
            )

        assert result[str(area_id)] == "Jane Doe"
        assert result["currentNameEditId"] == "00000000-0000-0000-0000-000000000000"
        assert len(result["nameHistory"]) == 1
        entry = result["nameHistory"][0]
        assert entry["id"] == "00000000-0000-0000-0000-000000000000"
        assert entry["name"] == "Jane Doe"
        assert entry["source"] == "WORKER"
        import re

        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", entry["editedAt"]
        )

    async def test_exam_name_empty_value_no_injection(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: []}, [area]
            )

        assert "nameHistory" not in result
        assert "currentNameEditId" not in result

    async def test_exam_name_none_value_no_injection(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.name = "EXAM_NAME"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value=None)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["1"]}, [area]
            )

        assert "nameHistory" not in result

    async def test_non_exam_name_metadata_unaffected(self, mock_scan_worker):
        area_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        choice_id = UUID("11111111-2222-3333-4444-555555555555")
        area = MagicMock()
        area.id = area_id
        area.area_type = MagicMock()
        area.area_type.choice_type_id = choice_id
        area.area_type.name = "ROOM"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(return_value="203")

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id: ["2", "0", "3"]}, [area]
            )

        assert result == {str(area_id): "203"}

    async def test_multiple_exam_name_areas_first_resolving_wins(self, mock_scan_worker):
        area_id_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        area_id_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        choice_a = UUID("11111111-2222-3333-4444-555555555555")
        choice_b = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")

        area_a = MagicMock()
        area_a.id = area_id_a
        area_a.area_type = MagicMock()
        area_a.area_type.choice_type_id = choice_a
        area_a.area_type.name = "EXAM_NAME"

        area_b = MagicMock()
        area_b.id = area_id_b
        area_b.area_type = MagicMock()
        area_b.area_type.choice_type_id = choice_b
        area_b.area_type.name = "EXAM_NAME"

        async def stringify(choice_type_id, local_ids):
            return "First" if choice_type_id == choice_a else "Second"

        api_client = AsyncMock()
        api_client.stringify_choices = AsyncMock(side_effect=stringify)

        with patch("worker.worker.scan.get_api_client", return_value=api_client):
            result = await mock_scan_worker._derive_metadata_payload(
                {area_id_a: ["1"], area_id_b: ["2"]},
                [area_a, area_b],
            )

        assert result["nameHistory"][0]["name"] == "First"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run -m pytest "tests/test_scan_worker.py::TestDeriveMetadataPayload" -v -k "exam_name or non_exam_name or multiple_exam_name"`
Expected: FAIL — `KeyError: 'currentNameEditId'` / `KeyError: 'nameHistory'` (injection not implemented yet)

- [ ] **Step 3: Modify `_derive_metadata_payload`**

In `worker/worker/scan.py`, change the return annotation on line 155 from:

```python
    ) -> dict[str, str]:
```

to:

```python
    ) -> dict[str, Any]:
```

Change the payload declaration (line 171) from:

```python
        payload: dict[str, str] = {}
```

to:

```python
        payload: dict[str, Any] = {}
```

Then locate this block (currently lines 216-221):

```python
            payload[str(area_id)] = stringified
            if logger is not None:
                await logger.info(
                    f"_derive_metadata_payload: area_id={area_id} choiceTypeId={choice_type_id} "
                    f"localIds={local_ids} -> stringified={stringified!r}"
                )
```

Replace it with:

```python
            payload[str(area_id)] = stringified
            if logger is not None:
                await logger.info(
                    f"_derive_metadata_payload: area_id={area_id} choiceTypeId={choice_type_id} "
                    f"localIds={local_ids} -> stringified={stringified!r}"
                )

            # An EXAM_NAME area's resolved value seeds the submission's editable
            # name + its history. First EXAM_NAME area with a non-empty value
            # wins; an empty value leaves the name unresolved (forces a draft
            # downstream for non-teacher scans).
            if (
                area.area_type.name == EXAM_NAME_AREA_TYPE
                and stringified
                and "nameHistory" not in payload
            ):
                payload["currentNameEditId"] = NIL_UUID
                payload["nameHistory"] = [
                    {
                        "id": NIL_UUID,
                        "name": stringified,
                        "editedAt": _iso8601_utc_now(),
                        "source": NAME_HISTORY_SOURCE_WORKER,
                    }
                ]
                if logger is not None:
                    await logger.info(
                        f"_derive_metadata_payload: EXAM_NAME area_id={area_id} "
                        f"-> seeded nameHistory name={stringified!r}"
                    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run -m pytest "tests/test_scan_worker.py::TestDeriveMetadataPayload" -v`
Expected: PASS — all tests in the class (existing 7 + new 5) pass. Existing tests use `MagicMock` areas whose `area_type.name` is an auto-MagicMock (never `== "EXAM_NAME"`), so no injection occurs and their exact-dict assertions still hold.

- [ ] **Step 5: Commit**

```bash
git add worker/worker/scan.py tests/test_scan_worker.py
git commit -m "feat: inject currentNameEditId + nameHistory for EXAM_NAME metadata"
```

---

## Task 5: Wire force-draft into the submission branch

**Files:**
- Modify: `worker/worker/scan.py` (~lines 766-780)
- Test: full suite (`tests/test_scan_worker.py`) — existing draft/direct integration tests must stay green

- [ ] **Step 1: Modify the branch**

In `worker/worker/scan.py`, locate this block (currently lines 766-779):

```python
                        # A "valid" scan result has a resolved studentId, every problem answered,
                        # and multi-answers only on multi-select problems. Valid results skip the
                        # draft phase even when student verification is enabled.
                        is_valid_result = self._is_valid_scan_result(
                            student_id, problem_results, problem_map, multi_select_by_area_id
                        )

                        # Branch based on studentVerificationEnabled, source, and scan validity.
                        # Teacher scans and valid scans always create ExamSubmission directly (skip draft phase).
                        recalculate_stats = False
                        if exam.student_verification_enabled and scan_request_source != "TEACHER" and not is_valid_result:
                            # Create DraftSubmission (student verification required, student scan only)
                            await logger.info("Creating DraftSubmission (studentVerificationEnabled=true, source=STUDENT)")
```

Replace it with:

```python
                        # A "valid" scan result has a resolved studentId, every problem answered,
                        # and multi-answers only on multi-select problems. Valid results skip the
                        # draft phase even when student verification is enabled.
                        is_valid_result = self._is_valid_scan_result(
                            student_id, problem_results, problem_map, multi_select_by_area_id
                        )

                        # An EXAM_NAME metadata area that did not resolve to a name
                        # forces a DraftSubmission so a human can fix it — except
                        # for TEACHER scans, which always go direct.
                        exam_name_unresolved = self._is_exam_name_unresolved(
                            metadata_areas, metadata_payload
                        )
                        force_draft_unresolved_name = self._force_draft_for_unresolved_name(
                            exam_name_unresolved, scan_request_source
                        )

                        # Branch based on studentVerificationEnabled, source, scan validity,
                        # and unresolved EXAM_NAME. Teacher scans and valid scans otherwise
                        # create ExamSubmission directly (skip draft phase).
                        recalculate_stats = False
                        if (
                            exam.student_verification_enabled
                            and scan_request_source != "TEACHER"
                            and not is_valid_result
                        ) or force_draft_unresolved_name:
                            # Create DraftSubmission (student verification required, or
                            # EXAM_NAME unresolved on a non-teacher scan)
                            if force_draft_unresolved_name:
                                await logger.info(
                                    "Forcing DraftSubmission: EXAM_NAME metadata unresolved (source != TEACHER)"
                                )
                            else:
                                await logger.info("Creating DraftSubmission (studentVerificationEnabled=true, source=STUDENT)")
```

- [ ] **Step 2: Run the full scan-worker suite**

Run: `uv run -m pytest tests/test_scan_worker.py -v`
Expected: PASS — all existing draft/direct tests (`test_full_job_with_submission`, `test_invalid_student_scan_creates_draft_submission`, `test_teacher_duplicate_submission_soft_deletes_and_recreates`, `test_student_duplicate_submission_fails_with_process_error`) plus all new tests pass. These integration tests have no EXAM_NAME area, so `exam_name_unresolved` is `False` and the branch behaves exactly as before.

- [ ] **Step 3: Commit**

```bash
git add worker/worker/scan.py
git commit -m "feat: force draft submission when EXAM_NAME metadata unresolved (non-teacher)"
```

---

## Task 6: Lint, type-check, full test run

**Files:** none (verification only)

- [ ] **Step 1: Lint**

Run: `uv run -m ruff check worker/`
Expected: no errors. If `Any` is flagged as unused in `scan.py`, confirm it is imported (line 10 already imports `Any` from `typing` — no change needed).

- [ ] **Step 2: Type-check**

Run: `uv run -m mypy worker/`
Expected: no new errors introduced by these changes.

- [ ] **Step 3: Full test suite**

Run: `uv run -m pytest`
Expected: all tests pass.

- [ ] **Step 4: Commit (only if lint/type fixes were needed)**

```bash
git add -A
git commit -m "chore: lint/type fixes for EXAM_NAME metadata feature"
```

---

## Self-Review Notes

- **Spec coverage:** detection via `area_type.name == "EXAM_NAME"` (Task 4); per-area key kept + `currentNameEditId`/`nameHistory` injected (Task 4); `nameHistory` fresh single-element list (Task 4); `"WORKER"` literal not in DB enum (Task 1 constant comment); ISO-8601 UTC ms+Z `editedAt` (Task 1); first-resolving EXAM_NAME wins (Task 4 `"nameHistory" not in payload` guard + test); force-draft for unresolved, TEACHER-exempt (Tasks 2, 3, 5); applies to both DraftSubmission and ExamSubmission since both assign the same `metadata_payload` (unchanged call sites, verified in Task 5 suite run). All spec requirements mapped.
- **Spec deviation (documented in Architecture):** the unresolved flag is derived from the payload via `_is_exam_name_unresolved` instead of changing `_derive_metadata_payload`'s return type. Identical observable behaviour; avoids regressing existing tests/call sites.
- **Type consistency:** `_iso8601_utc_now`, `_is_exam_name_unresolved`, `_force_draft_for_unresolved_name` names used identically across definition and call sites; constants `EXAM_NAME_AREA_TYPE`, `NIL_UUID`, `NAME_HISTORY_SOURCE_WORKER` consistent across `consts.py`, `scan.py`, and tests.
- **Placeholder scan:** none — every code step contains complete code.
