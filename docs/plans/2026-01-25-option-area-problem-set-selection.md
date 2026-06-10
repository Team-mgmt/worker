# Design: OPTION Area Detection for Problem Set Selection

## Problem

When no default problem set exists for an exam, the worker raises:
```
ProcessError("No default problem set found for exam")
```

The system should instead detect OPTION areas and use their marked values to select the appropriate problem set.

## Root Cause

OPTION areas are not processed by the image processor. Only IDENTIFIER and PROBLEM areas are detected, so `detected_by_area_id` never contains OPTION area detections. The problem set matching logic already supports matching by `area_id` + `area_value`, but OPTION detections are missing.

## Solution

Add OPTION area processing to the existing pipeline.

### Changes

#### 1. `worker/types.py`

Add `option_results` field to `ProcessResult`:

```python
class ProcessResult(TypedDict):
    # ... existing fields ...
    student_info_results: dict[int, list[str]]  # IDENTIFIER areas
    problem_results: dict[int, list[str]]       # PROBLEM areas
    option_results: dict[int, list[str]]        # NEW: OPTION areas
```

#### 2. `worker/processors/v1.py`

Process OPTION areas alongside IDENTIFIER and PROBLEM:

- Filter OPTION areas: `[a for a in areas if a.area_type.base_type == "OPTION"]`
- Call `_process_child_areas()` for OPTION areas
- Include results in `area_image_paths`, `area_metrics`, `annotations`
- Return `option_results` in `ProcessResult`

#### 3. `worker/worker/scan.py`

Include `option_results` when building `detected_by_area_id`:

```python
for idx, local_ids in process_result["option_results"].items():
    if idx in areas_map and local_ids:
        detected_by_area_id[areas_map[idx]] = local_ids[0]
```

### Files Changed

| File | Change |
|------|--------|
| `worker/types.py` | Add `option_results` field |
| `worker/processors/v1.py` | Process OPTION areas |
| `worker/worker/scan.py` | Include option_results in detection map |

### Backward Compatibility

- Exams without OPTION areas: unaffected (empty `option_results`)
- Exams with default problem set: continues to work as fallback
- Existing matching logic unchanged

### Testing

- Exam with OPTION area linked to problem sets (no default set)
- Student marks an option value
- Verify correct problem set is selected based on marked value
