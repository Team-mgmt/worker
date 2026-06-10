# OMR Downscale Risks And Safeguards

## Purpose

This document defines the main risks of introducing a low-resolution recognition path into the OMR pipeline, along with practical safeguards, rollout rules, and fallback criteria.

It is intended to prevent:

- silent accuracy regression
- over-aggressive morphology tuning
- ROI scaling mistakes
- optimistic assumptions about runtime improvement

## Main Principle

The downscale task should be treated as a controlled optimization, not as a free speed win.

That means:

- accuracy must be preserved first
- runtime improvement must be measured, not assumed
- fallback must be easy if the low-resolution path harms recognition quality

## Risk 1: Faint Mark Loss

### Description

When the recognition image is downscaled too aggressively, faint pencil marks may become too small or too weak to survive thresholding and morphology.

### Safeguards

- Do not start from an aggressively small recognition width.
- Use a conservative initial width such as `1400 ~ 1600 px` for A4-like templates.
- Validate against scans with known faint marks.
- Compare blank / faint-mark errors before and after on the same scan set.

### Rollout Rule

- If faint-mark false negatives increase materially, stop rollout and increase recognition width before any further tuning.

## Risk 2: Over-Aggressive Morphology

### Description

Kernel sizes that are too large after scaling may:

- merge nearby marks
- increase false positives
- distort bubble shape

Kernel sizes that are too small may:

- fail to close white holes
- leave noise unfiltered

### Safeguards

- Use width-based kernel scaling from a known high-resolution baseline.
- Force kernels to be odd integers.
- Clamp kernels to explicit minimum and maximum values.
- Prefer ellipse kernels over rectangular kernels.
- Start with `CLOSE -> OPEN`, not large `OPEN` first.

### Rollout Rule

- If false positives increase or bubble boundaries become visibly over-smoothed, reduce kernel size before changing other logic.

## Risk 3: White-Hole / Blob Fragmentation

### Description

Dark filled bubbles can still fragment after thresholding, especially at lower resolution.
This can reduce mark stability or shift feature distributions.

### Safeguards

- Prefer a small `MORPH_CLOSE` before `MORPH_OPEN`.
- Keep `close_ksize >= open_ksize`.
- Review threshold and area images for dark filled bubbles specifically.
- Benchmark on scans known to produce hole artifacts.

### Rollout Rule

- If dark filled marks show more internal holes after downscaling, pause rollout and retune close/open before merging.

## Risk 4: ROI Coordinate Scaling Errors

### Description

If parent and child coordinates are not scaled consistently, low-resolution ROI crops may drift away from the intended bubble location.

### Safeguards

- Use one shared recognition scale factor per image.
- Apply the same scale to:
  - area parent position
  - child relative position
  - child width / height
- Use a consistent rounding rule across all ROI coordinate calculations.
- Validate a sample of cropped area images visually in backoffice debug.

### Rollout Rule

- If ROI crops look systematically shifted or clipped, treat the implementation as invalid until coordinate scaling is corrected.

## Risk 5: Identifier Regression

### Description

Identifier areas are often denser and narrower than problem areas.
They are more sensitive to downscaling and morphology side effects.

### Safeguards

- Evaluate identifier accuracy separately from problem-answer accuracy.
- Keep identifier interpretation conservative.
- If needed, allow a higher minimum recognition width for identifier-heavy layouts.
- Do not assume problem-area tuning automatically works for identifier slots.

### Rollout Rule

- If identifier stability regresses meaningfully, block rollout even if problem-answer speed improves.

## Risk 6: Limited Runtime Gain

### Description

The codebase uses RoMaV2 with a fixed internal setting (`precise`), so image downscaling may not dramatically reduce matching inference time.

### Safeguards

- Do not describe this task as a guaranteed alignment speedup.
- Measure stage-level timings explicitly:
  - `alignment`
  - `warp`
  - `binarization`
  - `area_processing`
  - `TOTAL`
- Evaluate whether the runtime benefit actually comes from downstream processing.

### Rollout Rule

- If complexity increases but TOTAL runtime improvement is too small, reconsider the design or test a lighter RoMaV2 setting.

## Risk 7: Over-Generalizing One Good Setting

### Description

A recognition width and morphology setting that works on one paper layout may not transfer perfectly to others.

### Safeguards

- Validate on multiple scan batches, not just one.
- Include:
  - faint marks
  - dark marks
  - noisy scans
  - slightly skewed scans
  - identifier-heavy scans
- Record which paper types were used in evaluation.

### Rollout Rule

- If success is observed only on one narrow sample type, treat the result as provisional.

## Required Implementation Safeguards

These safeguards should be reflected directly in code where possible.

- Add `recognition_max_width` as an explicit parameter.
- Add `reference_template_width` as an explicit parameter.
- Add adaptive kernel scaling helper with clamp logic.
- Keep morphology ordering configurable.
- Keep logs detailed enough to compare before/after behavior.
- Avoid hidden hard-coded scale assumptions.

## Required Evaluation Safeguards

Before merge, confirm all of the following:

- same scan batch used for before/after comparison
- runtime measured at stage level
- answer accuracy reviewed
- identifier accuracy reviewed
- debug artifacts visually checked
- no major increase in false positives
- no major increase in faint-mark misses

## Fallback Strategy

If the low-resolution reading path causes unacceptable quality loss:

1. increase `recognition_max_width`
2. retune close/open kernel sizes
3. keep the downscaled path only for selected stages if necessary
4. if still unstable, fall back to the previous full-resolution reading path

If Strategy A is not accurate enough:

- do not force it into production
- either raise recognition resolution or test Strategy B

## Merge Gate

Do not merge the implementation unless:

- runtime improvement is measurable
- no material answer-reading regression is observed
- no material identifier regression is observed
- debug artifacts remain interpretable
- rollback remains straightforward

## Reviewer Questions

Before approval, reviewers should be able to answer:

1. What is the expected source of speedup in this codebase?
2. What is the most likely failure mode on faint marks?
3. What is the exact coordinate scaling rule?
4. What are the kernel min/max clamp rules?
5. What objective evidence shows that accuracy was preserved?
6. What is the fallback plan if Strategy A fails?

## Final One-Line Rule

Treat low-resolution OMR recognition as an optimization behind explicit safeguards: preserve accuracy first, scale morphology conservatively, validate on the same scan set, and keep fallback to the full-resolution path simple.
