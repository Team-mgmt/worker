# OMR Recognition Downscale Handoff

## Goal

The current OMR pipeline uses the full-resolution template image directly during recognition.
This is expensive and slows the pipeline down, especially when the template is a large print-grade PNG.

The goal of this task is:

- keep the print template at full resolution for authoring / printing
- introduce a lower-resolution recognition path for alignment and image processing
- reduce total processing time significantly
- preserve answer-reading quality by scaling morphology parameters correctly

This handoff describes the recommended implementation flow for another AI or engineer to review and continue.

## Important Correction About the Main Bottleneck

One important nuance for this codebase:

- the main runtime problem is **not necessarily RoMaV2 matching input size itself**
- the larger savings are more likely to come from:
  - full-frame warp output size
  - full-frame binarization
  - morphology
  - template decode / cache I/O

Why:

- `worker/matcher.py` initializes RoMaV2 with `apply_setting("precise")`
- that setting internally operates with fixed model resolutions
- therefore, passing a larger original image into RoMaV2 does not imply proportional matching cost at inference time

So this task should be framed primarily as:

- reducing downstream full-frame processing cost
- reducing full-resolution image handling cost
- not over-claiming speedup from RoMaV2 matching itself

## Current Pipeline Summary

The current student OMR flow in `worker/processors/v1.py` is:

1. load the scan image
2. detect QR codes
3. load the full-resolution template image
4. render QR codes onto the template
5. align scan to template with `RoMaV2`
6. binarize the warped scan and template
7. run morphology / residual analysis
8. crop child ROIs and decide marks

Important files:

- `worker/processors/v1.py`
  - main processor flow
  - binarization
  - ROI extraction
  - mark decision logic
- `worker/types.py`
  - processing parameter definitions
- `worker/matcher.py`
  - `RoMaV2` match / warp implementation

## Problem Statement

The current pipeline uses the large template image directly for recognition.
That means:

- full-frame binarization is larger than necessary
- morphology cost is higher than necessary
- full-frame warp output is larger than necessary
- template I/O and cache cost are also higher

Important:

- the RoMaV2 matching stage may not shrink much just by resizing the original image beforehand
- the most reliable speedups should come from reducing the size of the images used after alignment and during downstream preprocessing

The intended change is not to reduce print quality.
It is to decouple:

- print-resolution template
- recognition-resolution template

## Template Asset Strategy

The original template is authored as an Illustrator (vector) artwork and is
currently rasterized to a single high-resolution PNG that is used both for
print and for recognition. Two paths exist for introducing a low-resolution
recognition image:

### Option 1: runtime downsampling of the existing high-resolution PNG

- read the existing print PNG
- resize it to recognition width at job time
- requires no change to the template upload pipeline or storage layout

Pros:

- minimal infrastructure change
- easy to A/B test

Cons:

- repeated decode + resize cost on every job (mitigated by template cache)
- downsampling a high-resolution raster can leave anti-alias residue on
  bubble edges, which may slightly perturb thresholding

### Option 2: pre-rendered low-resolution recognition asset from the source vector

- at template registration time, render the vector source twice:
  - `background_image_print` — full print resolution (existing)
  - `background_image_recognition` — pre-rendered at the target recognition width
- store both, and have the worker load the recognition asset directly

Pros:

- cleaner edges (rasterized at the target resolution, no resample artifacts)
- no per-job resize cost
- smaller cache footprint and faster I/O for recognition

Cons:

- requires changes to the template upload pipeline and storage layout
- introduces a second asset that must be kept in sync with the print asset

### Recommended sequencing

- prototype Option 1 first to validate speed and accuracy quickly without
  touching upload / storage code
- if benchmarks show that resample artifacts hurt accuracy, or that
  per-job resize is a meaningful share of runtime, migrate to Option 2 as
  a follow-up

## Recommended Direction

Use a dual-resolution pipeline:

- keep `template_image_high` as the original print-resolution image
- create `template_image_low` for recognition
- create `scan_image_low` using the same scale
- run alignment on low-resolution images
- by default, keep the downstream warped image low-resolution as well

The primary objective is to reduce:

- warp output size
- binarization size
- morphology size
- ROI crop size

## Preferred Strategy

### Strategy A: align low, read low

This is the recommended default for this codebase when runtime reduction is the main goal.

Flow:

1. load the original scan and template images
2. resize both into recognition-resolution images:
   - `template_image_low`
   - `scan_image_low`
3. run alignment on the low-resolution pair
4. keep the warped output in low resolution
5. run binarization / morphology / ROI reading on `warped_image_low`
6. scale all template / child coordinates by the same recognition scale

Reason:

- this reduces almost every downstream full-frame operation
- `worker/processors/v1.py` already uses template-pixel child coordinates, so scaling them is straightforward
- the coordinate conversion risk is low because it is a direct uniform scale
- this is likely to produce a larger net speedup than keeping a high-resolution warp

## Less Preferred Strategy

### Strategy B: align low, read high

This is a fallback option when preserving final ROI fidelity is more important than maximizing speed.

Flow:

1. load `template_image_high`
2. load `scan_image_high`
3. resize both into `template_image_low` and `scan_image_low`
4. run alignment on the low-resolution pair
5. reuse the resulting warp on the original high-resolution scan
6. produce `warped_image_high`
7. run binarization / morphology / ROI reading on `warped_image_high`

Tradeoff:

- coordinate logic stays closer to the existing implementation
- but full-resolution warp, binarization, and morphology costs remain high
- this may deliver only a limited runtime improvement if RoMaV2 is not the dominant bottleneck

## Required Code Changes

### 1. Add recognition-resolution parameters

File:

- `worker/types.py`

Add parameters such as:

- `recognition_max_width: int = 1600`
- `reference_template_width: int = 2480`
- `adaptive_kernel_scaling: bool = True`
- `morph_close_first: bool = True`

Optional additional fields:

- `recognition_scale: float = 1.0`
- `recognition_interpolation: str = "area"`
- `min_kernel_size: int = 1`

Purpose:

- define the target width for recognition processing
- define the width on which current morphology tuning was originally calibrated
- make kernel scaling explicit and reproducible

### 2. Add image resize helper(s)

File:

- `worker/processors/v1.py`

Add helpers such as:

- `_resize_for_recognition(image, max_width) -> tuple[np.ndarray, float]`
- `_scaled_kernel_size(base_kernel, current_width, reference_width) -> int`

Recommended behavior:

- if image width is already smaller than `recognition_max_width`, keep scale `1.0`
- otherwise resize with `cv2.INTER_AREA`
- return both resized image and scale factor

### 3. Resize scan/template inside `process()`

File:

- `worker/processors/v1.py`

Recommended insertion point:

- after template load / QR rendering
- before `_align_scan_to_template(...)`

Suggested flow inside `process()`:

1. keep original:
   - `template_image_high`
   - `scan_image_high`
2. create:
   - `template_image_low, recognition_scale`
   - `scan_image_low`
3. align low:
   - `_align_scan_to_template(scan_image_low, template_image_low)`
4. if Strategy A is used:
   - continue with `warped_image_low`
   - scale ROI coordinates by `recognition_scale`
5. if Strategy B is used:
   - apply the low-resolution warp to `scan_image_high`
   - output `warped_image_high`

### 4. Update matcher to support warp reuse

File:

- `worker/matcher.py`

Current state:

- `warp_scan_to_template()` already accepts an optional `match_result`

Important note:

- a full new public API may not be necessary
- the current code may only need a lighter refactor or helper extraction
- this matters mainly for Strategy B

Why:

- the warp should be computed once at low resolution
- then re-applied to the high-resolution scan

Possible addition:

- a helper like `warp_scan_with_match_result(scan_image, template_shape, match_result)`

This helper should:

- take the original scan image
- resize / interpolate the dense warp field to the target template resolution
- apply `grid_sample` once to produce the final high-resolution warped image

If Strategy A is selected as the main path, this matcher work becomes optional rather than mandatory.

## Morphology Scaling Rules

### Basic kernel scaling formula

If the original morphology setting was tuned at width `W_ref` and the current recognition image width is `W_cur`, then:

`K_scaled = round(K_ref * W_cur / W_ref)`

Then force:

- odd integer
- lower bounded by at least `1` or `3` depending on operation

Recommended helper:

1. scale by width ratio
2. round to nearest integer
3. ensure odd
4. clamp to a minimum

Example:

- tuned at `2480 px`
- `close kernel = 5`
- recognition width = `1240 px`
- scaled kernel = about `3`

### Why width-based scaling is enough here

Since the page aspect ratio stays fixed during resize, width-ratio scaling and height-ratio scaling are effectively equivalent.
Width-based scaling is simpler and easier to reason about.

### Physical intuition for kernel sizes (for engineers without CV background)

The width-ratio formula above is mechanical. The underlying intuition is
that morphology kernels exist to manipulate features at a particular
**physical scale** — and the natural unit on an OMR sheet is the bubble.

A practical rule of thumb:

- a morphology kernel should be roughly `10 ~ 20%` of the bubble diameter
  at the working resolution
- `MORPH_CLOSE` size should be large enough to bridge typical white holes
  inside a filled bubble, but small enough not to merge separate bubbles
- `MORPH_OPEN` size should be large enough to erase isolated speckles
  but small enough not to eat into a thin pencil mark

Examples:

- if a bubble is about `30 px` wide at the recognition resolution,
  start with `close = 3 ~ 5`, `open = 1 ~ 3`
- if a bubble is about `60 px` wide, start with `close = 5 ~ 7`,
  `open = 3 ~ 5`

Why this matters here:

- the current kernel values were calibrated at the current full template
  resolution and **happen to fit** that resolution. They are not magic.
- when the working resolution changes, the bubble diameter in pixels
  changes proportionally, so kernel sizes must move with it.
- if in doubt, measure the bubble diameter on the recognition image once
  and pick kernel sizes from the rules above, rather than trusting
  inherited numbers.

## Morphology Strategy for Hole Prevention

Current issue:

- dark, heavily filled marks may contain white holes after thresholding

Recommended strategy:

- prefer `MORPH_CLOSE` before `MORPH_OPEN`

Reason:

- `CLOSE` fills small white holes inside dark blobs
- `OPEN` is better for removing isolated noise after the mark shape is stabilized

Suggested order:

1. adaptive threshold
2. small `MORPH_CLOSE`
3. optional small `MORPH_OPEN`
4. optional median blur

Practical rule:

- `close_ksize >= open_ksize`
- use ellipse kernels
- avoid aggressive opening on small downscaled bubbles

Example tuning idea:

- high-resolution baseline:
  - `close = 5`
  - `open = 3`
- low-resolution scaled:
  - `close = 3`
  - `open = 1 or 3`

## Binarization Update Recommendations

File:

- `worker/processors/v1.py`

Update `_binarize_document()` so that:

- kernel sizes are derived dynamically from the current working image width
- morphology order can be switched to `CLOSE -> OPEN`
- CLAHE remains optional

Suggested high-level flow:

1. LAB -> L channel
2. median blur
3. optional CLAHE
4. adaptive threshold
5. scaled `CLOSE`
6. scaled `OPEN`
7. optional post-threshold median blur

## Recognition Resolution Recommendation

There is no single universal number, but a practical target for OMR recognition is:

- about `1200 ~ 1800 px` template width for A4-like pages

Guideline:

- if full template width is around `2400 ~ 3500 px`, start with `1400 ~ 1600 px`
- if bubble diameter becomes too small after resize, increase slightly
- if alignment is still too slow, lower toward `1200 px`

For a DPI-style mental model:

- print may stay at `300 DPI`
- recognition often works well around `120 ~ 180 DPI`

For downstream recognition processing:

- start near `1400 px` width
- benchmark accuracy and runtime on the same scan set

Do not assume this width will dramatically reduce RoMaV2 matching time by itself.
The more reliable gain should come from reducing warped-image and preprocessing cost.

## Accuracy Hypothesis: Smaller May Also Mean Better

This task is framed primarily as a speed improvement, but there is a
plausible secondary hypothesis that **moderate downscaling may also
improve recognition accuracy**, not merely preserve it.

Possible mechanisms:

- scan-side noise (paper texture, dust, faint print, scanner sensor noise)
  is averaged out by `cv2.INTER_AREA` downsampling, so adaptive
  thresholding sees cleaner input
- bubbles become more compact blobs, so connected component analysis
  and `largest_blob_*` metrics become more stable
- residual subtraction (`warped ^ template`) is less sensitive to
  sub-pixel alignment errors when each pixel covers a larger physical
  region

Therefore the benchmark plan should not only ask "does accuracy stay the
same?" but also "**does accuracy as a function of recognition width have
a sweet spot below the current full resolution?**"

Concretely, sweep recognition width across e.g. `1000 / 1200 / 1400 /
1600 / 1800 / 2000 px` on the same scan batch and report both runtime
and accuracy at each point, instead of only comparing high-res vs one
chosen low-res.

## Recommended Implementation Order

### Phase 1

- add recognition-resolution parameters to `worker/types.py`
- add resize helper(s) to `worker/processors/v1.py`
- downscale scan/template before alignment
- scale child ROI coordinates for low-resolution reading

### Phase 2

- use Strategy A as the baseline implementation
- benchmark speed and answer stability
- confirm whether low-resolution reading is already sufficient

### Phase 3

- add adaptive kernel scaling helper
- move morphology toward `CLOSE -> OPEN`
- benchmark hole reduction on dark marks

### Phase 4

- only if necessary, implement Strategy B as a precision-preserving fallback
- optionally extract matcher helper(s) for explicit warp reuse
- compare Strategy A vs Strategy B on the same sample batch

### Phase 5

- validate speed improvement
- validate answer reading stability
- compare before/after on the same scan batch
- separately evaluate whether RoMaV2 `precise` setting should be replaced with a lighter setting if runtime remains too high

## Validation Checklist

Measure both runtime and reading quality.

Runtime checks:

- total job runtime
- alignment runtime
- warp runtime
- binarization runtime
- ROI processing runtime

Quality checks:

- does answer detection remain stable after downscaling?
- do heavily filled bubbles still show holes?
- do false positives increase?
- do identifier digits degrade?

Debug artifacts to inspect:

- warped image
- threshold image
- per-area ROI images
- per-problem metrics / logs

## Review Questions for Another AI

Please review the following specifically:

1. Is Strategy A the correct default architecture for this codebase?
2. Is the kernel scaling rule sufficient, or should kernel size be tied to measured bubble diameter instead of page width?
3. Is Strategy B worth the extra complexity, or is Strategy A enough in practice?
4. Should `worker/matcher.py` expose a lower-level warp application API, or is the existing `match_result` parameter sufficient?
5. Is `CLOSE -> OPEN` the correct default order for this OMR use case?
6. What recognition width would you recommend first for an A4-like template currently processed at full print resolution?
7. If runtime is still too high, would changing RoMaV2 from `precise` to a lighter setting likely matter more than further image downscaling?
8. Is there a measurable accuracy improvement (not just preservation) at lower resolution due to noise smoothing and reduced sensitivity to sub-pixel alignment errors? Benchmark accuracy as a function of recognition width, not just runtime.
9. Should the low-resolution recognition image be produced by downsampling the existing print PNG at runtime, or by pre-rendering a separate low-resolution PNG from the source vector at template registration time?

## Final One-Line Direction

Keep the print template at full resolution, but make low-resolution reading the default recognition path so that warp output, binarization, morphology, and ROI processing all get cheaper, while adaptively scaled `MORPH_CLOSE`-first processing preserves dark filled marks without holes.
