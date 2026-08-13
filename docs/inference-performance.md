# Inference performance optimization

## Baseline

The 34-spine shelf sample showed roughly 3.9-5.8 seconds per logged spine OCR on the
CPU-only EC2 instance. Matching took about 3 seconds, so OCR dominated the request.

Before this change, adaptive OCR performed:

- one full-spine OCR pass;
- one label-region OCR pass for every spine;
- up to three enhanced or rotated fallback passes.

That meant 68-170 PaddleOCR calls for a 34-spine image.

## Optimized behavior

Administrator analysis keeps adaptive OCR, but only runs the label-region and fallback
passes when the primary result has low confidence or no call number. A clear spine now
uses one OCR call while difficult spines retain the existing recovery path.

Patron target search already has a catalog title, author, and call number. It therefore
does not persist temporary crop JPEGs. Multiple rectified spines are combined into white-
gutter contact sheets before OCR, reducing 35 per-spine pipeline calls to 6 calls with the
default batch size of 6. OCR polygons are assigned back to the original spine by their
horizontal contact-sheet range. If contact-sheet OCR fails, the endpoint automatically
falls back to the compatible per-spine fast path.

Administrator analysis uses the same contact-sheet path for the primary OCR pass while
continuing to save individual crop JPEGs. Only low-confidence spines or spines without a
call number run the original label-region, enhancement, and rotation fallback passes.

The per-spine compatibility path can stop before the end of the shelf only when all of
these conditions hold:

- the normal `found` score and margin checks pass;
- total and title scores are at least 90;
- call-number score is at least 90 when a target call number exists;
- the call-number suffix does not conflict.

The response schemas and administrator `result.json` diagnostics remain unchanged.

The contact-sheet behavior can be tuned without a code change:

```env
OCR_CONTACT_SHEET_BATCH_SIZE=6
OCR_CONTACT_SHEET_GUTTER=24
```

On small CPU instances, start with 4-6. Larger batches reduce pipeline calls but increase
peak image memory and may resize very wide sheets more aggressively inside text detection.

The administrator catalog endpoint also caches exact result counts for 60 seconds. Page
rows and counts execute concurrently on a cache miss, and page navigation reuses the
count for the same library and normalized query.

## Deployment verification

After pulling and restarting the backend and worker, follow target-search timings:

```bash
sudo journalctl -u shelfalign-worker.service -f --no-pager -o cat | \
  grep --line-buffered -E 'find_target_book.*(early stop|status=)'
```

The final line includes `spines`, `ocr_spines`, `detection`, `ocr`, and `total`. For a
confident match before the shelf end, `ocr_spines` should be smaller than `spines`.

For administrator analysis, compare OCR attempts in the saved `result.json`. Clear
spines should normally report `ocr_attempt_count: 1`; difficult spines may report more.
Always compare target Top-1 accuracy and administrator call-number accuracy before and
after the change on the same images.
