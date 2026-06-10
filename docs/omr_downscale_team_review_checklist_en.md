# OMR Downscale Team Review Checklist

## Scope Check

- Confirm the goal is overall OMR runtime reduction, not only RoMaV2 matching acceleration.
- Confirm the implementation uses low-resolution recognition processing intentionally.
- Confirm print-resolution assets remain unchanged for authoring / printing.

## Code Review Check

- `worker/types.py`
  - New recognition-resolution parameters are clearly named.
  - Defaults are safe and backward-compatible.
  - Kernel-scaling reference values are explicit.

- `worker/processors/v1.py`
  - Resize helper is simple and deterministic.
  - Recognition scale is applied consistently.
  - ROI coordinate scaling is correct for child areas.
  - Binarization path uses adaptive kernel scaling.
  - Morphology order is intentional and configurable.
  - Logging remains useful and not excessively noisy.

- `worker/matcher.py`
  - No unnecessary complexity was added if Strategy A is the main path.
  - Any warp reuse helper is justified by actual use.
  - Existing alignment behavior remains understandable.

## Runtime Check

- Compare `Timing breakdown` logs before and after.
- Confirm `TOTAL` runtime improved on the same scan batch.
- Confirm `binarization` improved.
- Confirm `area_processing` improved.
- Confirm expectations for `alignment` are realistic.
- Confirm there is no unexpected regression in `save_images` or `annotate_images`.

## Accuracy Check

- Compare the same scans before and after.
- Verify answer-reading accuracy is not degraded.
- Verify faint-mark detection did not regress.
- Verify identifier stability did not regress.
- Verify blank scans remain controlled.
- Verify multi-mark ambiguity behavior is still acceptable.

## Morphology Check

- Verify `MORPH_CLOSE -> OPEN` improves hole filling on dark marks.
- Verify noise removal is still adequate.
- Verify small bubbles are not over-eroded after downscaling.
- Verify kernel scaling behaves sensibly at target recognition widths.

## Backoffice Check

- Open the same scan job type in backoffice.
- Review:
  - job logs
  - threshold image
  - flattened image
  - area images
  - area metrics
- Confirm debug artifacts are still useful for operators.

## Merge Safety Check

- Confirm the branch contains only intended files for this task.
- Confirm unrelated local changes are not mixed into the PR.
- Confirm tests relevant to the changed code were run.
- Confirm lint / type check passed.
- Confirm rollback plan is clear.

## Rollback Check

- Confirm the previous `develop` commit is known.
- Confirm reverting the PR is possible with a normal Git revert.
- Confirm no irreversible migration or data format change is included.

## Final Team Decision

- Approve for PR
- Approve with follow-up tasks
- Request changes

### Reviewer Notes

- Reviewer:
- Date:
- Main concern:
- Main confidence point:
- Required follow-up:
