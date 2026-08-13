# Shelf-order placement evaluation

ShelfAlign evaluates book-spine detection and shelf placement separately. Existing
`ground-truth.json` files remain valid; placement evaluation is enabled when an
annotation includes `placement_status`.

## Ground-truth set

Keep Nowon (`111058`) and Dobong (`111189`) runs in separate result groups. At a
minimum, collect these four conditions for each library:

1. a correctly ordered shelf;
2. one book moved out of call-number order;
3. one book from a clearly different KDC range;
4. one or more blurred, occluded, or unreadable call-number labels.

For every visible spine, correct the polygon, title, author, and call number in the
GT editor, then set **배치 정답** to `정상` or `오배열`. Do not infer the label from
the model prediction. Use the physical shelf arrangement as ground truth.

The saved annotation shape is backward compatible:

```json
{
  "id": "spine-3",
  "class": "book_spine",
  "polygon": [[0, 0], [10, 0], [10, 100], [0, 100]],
  "title": "example",
  "author": "author",
  "call_number": "813.6 주67ㅅ",
  "placement_status": "misplaced"
}
```

## Current shelf-order rule

The worker converts a call number into an ascending key containing:

- numeric KDC class number;
- Unicode-normalized author/book symbol split into text and numeric tokens;
- no copy or volume suffix (`c.2`, `v.2`, and similar suffixes are ignored).

Unreadable and class-only labels are excluded. The worker reports an automatic
misplacement only when at least four labels are parseable and removing exactly one
book restores the remaining sequence to ascending order. It abstains on ambiguous
adjacent swaps instead of arbitrarily blaming one of the two books.

This rule supplements the existing KDC-range rule and preserves the existing API
`decision` values. An unambiguous order outlier is returned as
`suspected_misplacement`.

## Metrics

Saving GT continues to calculate detection Precision, Recall, F1, AP50, and IoU.
When placement labels exist, it additionally stores:

- placement Precision;
- placement Recall;
- placement F1;
- TP, FP, FN, and TN.

The placement prediction and GT annotation are aligned by polygon IoU 0.5. Report
metrics per library and per difficulty condition; do not publish only a combined
average.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_shelf_order_service.py tests/test_detection_evaluation_service.py
.\.venv\Scripts\python.exe -m ruff check worker/services/shelf_order_service.py worker/services/detection_evaluation_service.py worker/schemas/artifact_evaluation.py tests/test_shelf_order_service.py tests/test_detection_evaluation_service.py
cd web
pnpm --filter @shelfalign/backoffice check-types
```

Success requires all unit tests and targeted lint/type checks to pass, plus the
four-condition GT set to show no false placement alarm on the normal shelf and a
detected outlier in both intentional-misplacement conditions.
