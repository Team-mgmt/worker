# Patron target-book search MVP

The patron flow is separate from the librarian full-catalog matching flow.

1. `GET /api/public/library-books` searches at most ten holdings in one supported library.
2. The patron selects one holding.
3. `/scan` uploads a shelf image and the selected title, author, call number, ISBN, and holding ID to
   `POST /worker/inference/find_target_book`.
4. The worker detects/OCRs the spines and compares each OCR result directly with that target.
5. The UI reports `found`, `possible`, or `not_found` and highlights the best spine.

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
