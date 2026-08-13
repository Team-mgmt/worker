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
uses one OCR pass per inspected spine and does not persist temporary crop JPEGs. It can
stop before the end of the shelf only when all of these conditions hold:

- the normal `found` score and margin checks pass;
- total and title scores are at least 90;
- call-number score is at least 90 when a target call number exists;
- the call-number suffix does not conflict.

The response schemas and administrator `result.json` diagnostics remain unchanged.

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

