# DB matching ablation harness

This harness compares four catalog reranking strategies on the same reviewed
OCR/GT cases and the same RDS candidate pools.

| Strategy | Score |
|---|---|
| `baseline` | RapidFuzz `token_sort_ratio` on the untrimmed OCR/catalog title |
| `preprocessed_fuzzy` | core-title normalization + compact RapidFuzz ratio |
| `tfidf` | core-title normalization + character 2/3-gram TF-IDF cosine |
| `final` | fuzzy + TF-IDF title, author, KDC, and book-code score |

## Input

Point `--artifact-root` at a local directory containing S3 run directories.
Each evaluated run must contain both `result.json` and `ground-truth.json`.
The GT annotations should contain the reviewed `LibraryHolding.id`; title and
call-number fallback is supported, but IDs are the reliable matching truth.

The harness polygon-aligns predictions and annotations at IoU 0.5, then queries
RDS again with the OCR fields. Evaluation combines exact-call-number rows with
all rows in the recognized full KDC class. It removes the noisy book-code-prefix
requirement and the production 1,500-row limit, then deduplicates holdings. All
four strategies therefore receive the same broader candidate pool.

Example download for one library:

```bash
aws s3 sync \
  s3://YOUR_BUCKET/shelfalign/scans/111058/ \
  ./outputs/ablation-artifacts/111058/ \
  --exclude "*" \
  --include "*/result.json" \
  --include "*/ground-truth.json"
```

Run from the repository root with the same `DATABASE_URL` used by the worker:

```bash
python -m worker.scripts.evaluate_matching_ablation \
  --artifact-root ./outputs/ablation-artifacts \
  --output ./outputs/matching-ablation.json \
  --markdown ./outputs/matching-ablation.md
```

Run both libraries separately for the presentation, even though the JSON also
contains a `libraries` breakdown:

```bash
python -m worker.scripts.evaluate_matching_ablation \
  --artifact-root ./outputs/ablation-artifacts/111058 \
  --output ./outputs/nowon-ablation.json \
  --markdown ./outputs/nowon-ablation.md

python -m worker.scripts.evaluate_matching_ablation \
  --artifact-root ./outputs/ablation-artifacts/111189 \
  --output ./outputs/dobong-ablation.json \
  --markdown ./outputs/dobong-ablation.md
```

## Metrics

- Top-1 and Top-3 catalog accuracy
- normalized OCR title accuracy
- exact normalized call-number accuracy
- confirmed and wrongly confirmed counts
- false-confirmation rate
- mean and nearest-rank P95 reranking latency
- candidate-pool miss count

Title and call-number OCR accuracy do not change across reranking strategies;
they are repeated beside each row so the quality of the fixed OCR input remains
visible. Latency measures Python reranking only. It excludes DB query, YOLO, and
OCR latency and must not be presented as end-to-end inference latency.

`candidate_pool_miss_count` is essential: if the correct holding is absent from
the SQL candidate pool, no reranker can recover it. Report this separately from
Top-1 errors. Do not claim an improvement from one or two shelf images; use a
fixed reviewed set and keep Nowon (`111058`) and Dobong (`111189`) results
separate.

## Verification

```bash
python -m pytest \
  tests/test_matching_ablation_service.py \
  tests/test_matching_service.py \
  tests/test_matching_evaluation_service.py -q
```
