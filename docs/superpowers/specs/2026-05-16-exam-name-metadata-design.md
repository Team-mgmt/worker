# EXAM_NAME metadata → name-history injection + force-draft

Date: 2026-05-16
Branch: feat/otel-traces (work to be done on a dedicated branch)
Status: Approved design — pending implementation plan

## Problem

The worker stringifies every METADATA area's bubble detections and stores the
result in `DraftSubmission.metadata_` / `ExamSubmission.metadata_`, keyed by the
area UUID (`worker/worker/scan.py` `_derive_metadata_payload`, lines 150–223).

shelfalign-web has a submission "name editing" feature backed by two metadata fields:
`currentNameEditId` and a `nameHistory` array. When a metadata area represents
the exam taker's name, the worker should seed those fields from the scanned
value so the name flows through the editing UI with a proper history entry,
attributed to the worker.

Additionally, a submission must not be created as a *direct* `ExamSubmission`
when the exam name could not be resolved — it should fall back to a
`DraftSubmission` so a human can correct it (except teacher scans, which always
go direct).

## Detection rule

A metadata area is an "exam name" area when:

```python
area.area_type.name == "EXAM_NAME"   # exact string literal
```

`area.area_type.name` (`ExamPaperAreaType.name`) is already eagerly available on
each `ExamPaperArea` in `_derive_metadata_payload`. No API or schema change is
required. `stringify_choices` continues to return a plain `str`; the resolved
name is exactly that stringified value.

## Behaviour

### Payload injection

For an EXAM_NAME area, the existing per-area entry is **still written**
unchanged:

```python
payload[str(area_id)] = stringified
```

Additionally, when an EXAM_NAME area resolves to a **non-empty** name, the
following top-level keys are set on the same `metadata` dict:

```python
NIL_UUID = "00000000-0000-0000-0000-000000000000"

payload["currentNameEditId"] = NIL_UUID
payload["nameHistory"] = [
    {
        "id": NIL_UUID,
        "name": <resolved name>,
        "editedAt": <now, ISO 8601 UTC, millisecond precision, "Z" suffix>,
        "source": "WORKER",
    }
]
```

- `nameHistory` is always a fresh, single-element list. The worker has no prior
  history to merge; it owns index 0 only.
- `"WORKER"` is a plain JSON string literal in the metadata JSONB. It is **not**
  added to the `Scansource` DB enum (`STUDENT`, `TEACHER`), which is unrelated.
- `editedAt` is produced as a UTC ISO 8601 string with millisecond precision and
  a `Z` suffix (e.g. `2026-05-16T12:34:56.789Z`), independent of the naive
  `datetime.now()` used elsewhere in `scan.py` for DB columns. A small helper
  produces this string.
- This injection applies to both `DraftSubmission.metadata_` and
  `ExamSubmission.metadata_`, since both are assigned the same `metadata_payload`
  (lines 878 and 991).

### Multiple EXAM_NAME areas

The **first** EXAM_NAME area (by iteration order over `metadata_results`) that
yields a non-empty resolved name wins: its value populates `currentNameEditId`
and `nameHistory`. Later EXAM_NAME areas do not overwrite it. The result is
considered unresolved only if **no** EXAM_NAME area produced a non-empty name.

### Resolution status & force-draft

`_derive_metadata_payload`'s return type changes from `dict[str, str]` to a
result carrying both the payload and a flag:

- `payload: dict[str, object]` (now also holds the list/dict name-history value)
- `exam_name_unresolved: bool` — `True` iff at least one EXAM_NAME area exists
  **and** none of them produced a non-empty resolved name. "Unresolved" covers:
  `stringify_choices` returning `None`, returning `""`, raising, or the area
  having no `choice_type_id`.

If there is no EXAM_NAME area at all, `exam_name_unresolved` is `False` (the
feature is inert; nothing changes).

The branch at `scan.py:777` is extended. Today:

```python
if exam.student_verification_enabled and scan_request_source != "TEACHER" and not is_valid_result:
    # DraftSubmission
else:
    # ExamSubmission (direct)
```

becomes:

```python
force_draft_unresolved_name = exam_name_unresolved and scan_request_source != "TEACHER"
create_draft = (
    exam.student_verification_enabled
    and scan_request_source != "TEACHER"
    and not is_valid_result
) or force_draft_unresolved_name

if create_draft:
    # DraftSubmission
else:
    # ExamSubmission (direct)
```

- TEACHER scans are **exempt**: an unresolved EXAM_NAME never forces a teacher
  scan into a draft. Teacher scans still get name-history keys injected when the
  name *does* resolve.
- A log line is emitted when the unresolved-name override is what forces the
  draft (distinct from the existing verification-driven draft log).

## Data flow

```
process_result.metadata_results
  → _derive_metadata_payload(...)            # stringify per area
       ├─ detect EXAM_NAME via area_type.name
       ├─ inject currentNameEditId + nameHistory (first resolving area)
       └─ compute exam_name_unresolved
  → (metadata_payload, exam_name_unresolved)
  → branch decision (force-draft if unresolved & not TEACHER)
  → DraftSubmission.metadata_ / ExamSubmission.metadata_ = metadata_payload
```

## Error handling

Consistent with the existing "metadata is auxiliary, skip per-area, don't fail
the scan" philosophy. An unresolved EXAM_NAME does not raise — it degrades the
submission to a draft (for non-teacher scans) so a human resolves the name.

## Files touched

- `worker/worker/scan.py`
  - `_derive_metadata_payload`: detection, injection, return-type change.
  - Branch at ~777: `create_draft` computation + override log line.
  - New module-level constants: `NIL_UUID`, EXAM_NAME literal, source literal;
    ISO 8601 UTC timestamp helper.
- `tests/test_scan_worker.py`
  - Update existing `_derive_metadata_payload` tests for the new return type.
  - Add: EXAM_NAME resolves → per-area key + `currentNameEditId` + `nameHistory`
    shape correct; `exam_name_unresolved` False.
  - Add: EXAM_NAME stringify `None`/`""` → no name keys; `exam_name_unresolved`
    True.
  - Add: no EXAM_NAME area → no name keys; `exam_name_unresolved` False;
    non-EXAM_NAME metadata areas unaffected.
  - Add: multiple EXAM_NAME areas → first resolving wins.
  - Add branch tests: unresolved EXAM_NAME forces DraftSubmission for non-teacher
    scans even when verification disabled / result valid; TEACHER scan with
    unresolved EXAM_NAME still creates ExamSubmission; resolved EXAM_NAME on an
    otherwise-direct path still creates ExamSubmission with name keys present.

## Out of scope

- Any shelfalign-web change. The metadata shape (`currentNameEditId`, `nameHistory`
  entry keys, `"WORKER"` source) is assumed to match shelfalign-web's expectations.
- Merging with pre-existing `nameHistory` (worker always writes a fresh list).
- Adding `"WORKER"` to the `Scansource` enum or any DB migration.
