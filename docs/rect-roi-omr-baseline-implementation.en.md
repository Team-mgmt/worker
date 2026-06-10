# Rect ROI OMR Baseline Implementation

## Overview

This change introduces a new rectangular ROI-based bubble measurement mode for OMR detection.

The implementation is intended for the updated answer sheet template (`new_template`) where the left and right bubble borders are removed to reduce false positives caused by printed borders being counted as fill.

The existing ellipse-based bubble measurement mode is preserved as a fallback, but the new implementation adds:

- rectangular ROI measurement
- baseline offset support (`+10%`)
- ROI-local morphology experiment options
- explicit separation between raw and adjusted baseline values

## Problem Definition

The main false-positive source in the previous OMR flow was not only the printed digit inside the bubble, but also the left and right bubble borders being included in fill-ratio measurement.

This became more visible when:

- the template was rendered from SVG into raster form
- the rendered bubble strokes appeared thicker than the original SVG geometry
- unfilled bubbles still produced relatively high fill ratios

In practice, an unfilled bubble could look significantly darker than its SVG baseline, especially after rasterization or photo-based processing.

## Design Goal

The new implementation aims to:

- reduce the effect of left/right bubble borders
- measure a more relevant inner region of the bubble
- preserve template-baseline delta logic
- keep the legacy ellipse path available for fallback and comparison

## High-Level Behavior

### Previous flow

1. Backoffice stores a child bbox for each bubble.
2. Worker measures fill ratio inside an ellipse mask derived from that bbox.
3. Template baseline and scanned fill ratio are compared in the same ellipse-style measurement path.

### New flow

1. Backoffice still stores the same bubble bbox.
2. Worker can measure fill ratio using a rectangular ROI instead of an ellipse mask.
3. Template baseline is measured using the same rectangular ROI.
4. A baseline offset is applied before delta calculation.
5. Optional morphology can be applied locally to the ROI before measurement.

## Main Changes

### 1. New measurement shape

Added a new bubble measurement shape:

- `ellipse`
- `rect`

`ellipse` is the legacy behavior.

`rect` is the new mode intended for the new template shape.

### 2. Rectangular ROI measurement

In `rect` mode, the worker no longer applies an ellipse mask for bubble measurement.

Instead, it reads the bubble bbox as a rectangular region and computes the fill ratio directly from that ROI.

This aligns better with the new template where left/right side walls are removed and the effective fill area is closer to a rectangular vertical region than a closed ellipse.

### 3. Baseline offset

Added a baseline offset parameter:

- `baseline_fill_ratio_offset = 0.10`

Decision-time baseline is now:

```text
adjusted_baseline_fill_ratio = baseline_fill_ratio + baseline_fill_ratio_offset
```

Delta is computed as:

```text
delta_fill_ratio = fill_ratio - adjusted_baseline_fill_ratio
```

The purpose of the offset is to absorb the apparent stroke thickening that can happen after SVG rasterization or bitmap-like rendering.

### 4. Raw baseline vs adjusted baseline

The implementation explicitly separates:

- `baseline_fill_ratio`
  - raw template baseline actually measured from the template
- `adjusted_baseline_fill_ratio`
  - the baseline value used in final decision after applying the offset

This prevents confusion during debugging and result analysis.

### 5. ROI-local morphology options

Added ROI-specific morphology experiment parameters:

- `bubble_roi_use_morphology`
- `bubble_roi_morph_close_first`
- `bubble_roi_morph_open_ksize`
- `bubble_roi_morph_close_ksize`

These are intentionally separate from document-level morphology options so ROI tuning does not implicitly depend on unrelated full-image threshold settings.

Morphology is optional and disabled by default.

## File-Level Changes

### `worker/types.py`

Added and updated:

- `BubbleShape = Literal["ellipse", "rect"]`
- `baseline_fill_ratio_offset`
- `bubble_measurement_shape`
- ROI morphology parameters
- `adjusted_baseline_fill_ratio` in `AreaMetrics`

### `worker/processors/v1.py`

Added:

- rectangular ROI measurement helpers
- ROI-local morphology helper
- measurement branching by `bubble_measurement_shape`
- baseline offset application in delta mode
- raw / adjusted baseline metric recording

Updated behavior:

- `fill_ratio`, `baseline_fill_ratio`, and `delta_fill_ratio` are all computed using the same measurement shape
- `processing_meta.bubble_shape` records the runtime measurement mode

### `worker/cache.py`

Updated template baseline cache key inputs to include:

- measurement shape
- ROI morphology flags
- ROI morphology kernel sizes
- ROI morphology order

This ensures cached template baselines remain aligned with the actual measurement configuration.

### Tests

Updated / added tests in:

- `tests/test_types.py`
- `tests/test_processors_v1.py`
- `tests/test_cache.py`
- `tests/test_scan_worker.py`

Coverage additions included:

- rect ROI delta mode
- rect ROI absolute mode
- scanned rect measurement excluding template ink
- cache-key separation for ROI settings
- scan submission flow coverage for draft / duplicate / teacher priority branches

## Service Flow Impact

### What did not change

- Backoffice still stores bubble coordinates as bbox values.
- Existing ellipse-based measurement remains available.
- Template-driven baseline caching still exists.

### What changed

- Worker can now interpret the same bbox as a rectangular ROI.
- Baseline and scanned fill are measured using the same rect ROI.
- Final delta uses adjusted baseline rather than raw baseline.

## Expected Effects

- reduced influence of left/right printed borders
- lower false positives on unfilled bubbles
- more stable delta separation for the new template
- better alignment between template design and worker-side measurement logic

## Notes

- This change does not remove the legacy ellipse path.
- This change does not yet introduce bitmap-baseline mode as a separate baseline source.
- ROI morphology is implemented as an experiment option, not as a forced default.

## Validation

The following validations were performed during implementation:

- `ruff` on worker and related tests
- targeted pytest runs for processors, cache, and scan worker test files

`mypy worker/` still reports an unrelated existing `worker/text_render.py` issue already present on `develop`, caused by a generated model/schema mismatch for `Exam`.

