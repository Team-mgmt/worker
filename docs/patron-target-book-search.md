# Patron target-book search MVP

The patron flow is separate from the librarian full-catalog matching flow.

1. `GET /api/public/library-books` searches at most ten holdings in one supported library.
2. The patron selects one holding.
3. `/scan` uploads a shelf image and the selected title, author, call number, ISBN, and holding ID to
   `POST /worker/inference/find_target_book`.
4. The worker detects/OCRs the spines and compares each OCR result directly with that target.
5. The UI reports `found`, `possible`, or `not_found` and highlights the best spine.

The same `/scan` page also supports a short patron video without replacing the image flow:

1. The patron records or selects a video of at most 15 seconds.
2. `POST /worker/inference/find_target_book_video` samples the video every second.
3. It chooses up to three sharp frames with temporal spacing instead of analyzing every frame.
4. Frames are checked in playback order with the existing target-image pipeline.
5. Processing stops as soon as one frame reaches `found`; otherwise the strongest reviewed result is returned.
6. The UI shows only the selected target result, winning frame, timestamp, and target candidate boxes. It does
   not expose a catalog list for every other detected spine.

Video artifacts are written asynchronously below `shelfalign/videos/{library_code}/...`: the original video,
analyzed frames, annotated winning frame, and `result.json`. This makes false positives and target-missing
videos available for later GT review without adding S3 upload time to the HTTP response.

No vector model or GPU is required. The MVP combines normalized RapidFuzz title/author similarity with
structured KDC and book-code similarity. The call-number score separates KDC, the author-number stem,
and the final title symbol; a different final symbol receives an additional penalty. When a call number
is available, weights are call number 45%, title 45%, and author 10%; otherwise title is 80% and author
20%.

An ambiguous `possible` response returns its top two candidates. The patron UI marks both in amber so it
does not visually assert that a single uncertain candidate is the requested book.

Temporary, uncalibrated thresholds are:

- `found`: score at least 82 and a Top-1/Top-2 margin of at least 10;
- `possible`: score at least 65;
- `not_found`: below 65.

Every response contains `calibration_status: "uncalibrated"`. These values must not be described as
measured accuracy until target-present and target-absent GT images exist.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_target_matching_service.py
cd web
pnpm --filter @shelfalign/backend test -- --runInBand src/routes/public/library-books/library-books.controller.spec.ts
pnpm --filter @shelfalign/backend check-types
pnpm --filter @shelfalign/backoffice check-types
```

After deployment, open `/scan`, search for a holding, select it, and upload both a target-present image
and a target-absent image. Record the response status, best score, margin, total latency, and whether the
highlighted bounding box is correct.

For video verification, repeat both cases with a 5-15 second sweep. Confirm that the returned timestamp
corresponds to the displayed frame, `analyzed_frame_count` is at most three, and a confident early frame
prevents later frames from being analyzed.
