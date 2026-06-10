# OMR Downscale Before/After Evaluation Template

## Purpose

Use this template to compare the current `develop` behavior against the new recognition-downscale implementation on the same scan set.

The goal is to evaluate:

- runtime improvement
- answer-reading stability
- identifier stability
- morphology side effects

## Test Metadata

- Evaluator:
- Date:
- Branch / commit under test:
- Baseline branch / commit:
- Scan batch name:
- Number of scans:
- Exam paper type:
- Notes:

## Runtime Summary

Fill this table using the same scan batch for both baseline and candidate runs.

| Metric | Baseline | Candidate | Delta | Delta % | Notes |
|---|---:|---:|---:|---:|---|
| Avg TOTAL ms |  |  |  |  |  |
| P50 TOTAL ms |  |  |  |  |  |
| P95 TOTAL ms |  |  |  |  |  |
| Avg alignment ms |  |  |  |  |  |
| Avg warp ms |  |  |  |  |  |
| Avg binarization ms |  |  |  |  |  |
| Avg area_processing ms |  |  |  |  |  |
| Avg annotate_images ms |  |  |  |  |  |
| Avg save_images ms |  |  |  |  |  |

## Runtime Interpretation

- Did TOTAL runtime improve?
- Which stage changed the most?
- Did alignment remain mostly flat?
- Did binarization and area processing drop as expected?
- Any regressions in outlier scans?

## Accuracy Summary

| Metric | Baseline | Candidate | Delta | Notes |
|---|---:|---:|---:|---|
| Problem answer accuracy |  |  |  |  |
| Identifier accuracy |  |  |  |  |
| Blank false positives |  |  |  |  |
| False negatives on faint marks |  |  |  |  |
| Multi-mark ambiguity cases |  |  |  |  |

## Per-Scan Comparison Table

Use one row per scan when comparing a representative subset.

| Scan ID | Baseline TOTAL ms | Candidate TOTAL ms | Baseline studentId | Candidate studentId | Baseline answer diff | Candidate answer diff | Pass/Fail | Notes |
|---|---:|---:|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |

## Debug Artifact Review

Review the same scans in backoffice job detail and compare:

- logs
- threshold image
- flattened image
- area images
- `area_metrics.json`
- `annotations_cropped.json`

### Questions

- Did heavily filled bubbles keep their shape after downscaling?
- Did white holes inside dark marks decrease?
- Did noise blobs increase?
- Did ROI crops remain centered enough after scaling?
- Did identifier slots become less reliable?

## Decision Log Review

Check problem-level logs for:

- `best`
- `second`
- `selected`
- `reason`

Notes:

- Are the reasons consistent with the visual ROI?
- Are ambiguous scans correctly marked as ambiguous?
- Are blank scans staying blank?

## Acceptance Criteria

Mark each item as pass or fail.

| Check | Pass/Fail | Notes |
|---|---|---|
| TOTAL runtime improved materially |  |  |
| No major drop in answer accuracy |  |  |
| No major drop in identifier accuracy |  |  |
| No visible increase in false positives |  |  |
| Hole artifacts improved or stayed controlled |  |  |
| Debug artifacts remain understandable |  |  |

## Final Recommendation

- Recommendation:
  - Merge
  - Merge with follow-up
  - Do not merge yet
- Summary:
- Main benefit observed:
- Main risk observed:
- Follow-up actions:
