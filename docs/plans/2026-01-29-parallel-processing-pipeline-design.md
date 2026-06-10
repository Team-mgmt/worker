# Parallel Processing Pipeline Design

**Date:** 2026-01-29
**Status:** Draft
**Author:** Claude + swjeon

## Overview

Redesign the scan processing architecture from a single monolithic worker to a 3-stage pipeline that:

- Separates CPU-bound and GPU-bound work
- Enables batch GPU inference for same-template scans
- Allows cost optimization via cheap CPU-only instances for stages 1 and 3

## Current Architecture

```
ScanRequest → [Single Worker: QR + Alignment + Detection] → Submission
                        (GPU instance)
```

**Problems:**

- GPU instance does CPU-bound work (QR detection, binarization)
- No batching - each scan processed individually
- Can't scale CPU and GPU work independently

## Proposed Architecture

```
┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│  Stage 1 (CPU)      │       │  Stage 2 (GPU)      │       │  Stage 3 (CPU)      │
│  -preprocess        │       │  (default)          │       │  -postprocess       │
│                     │       │                     │       │                     │
│  - Download image   │──────▶│  - Batch by template│──────▶│  - Binarization     │
│  - QR detection     │ meta  │  - RoMaV2 inference │ meta  │  - Area detection   │
│  - Parse metadata   │ only  │  - Upload warped    │+S3 key│  - Scoring          │
│                     │       │                     │       │  - Create submission│
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘
         │                             │                             │
         ▼                             ▼                             ▼
    S3 (read)                   S3 (read+write)                S3 (read+write)
    - scan image                - scan image                   - warped image
                                - template (cached)            - result images
                                - warped image
```

## Data Flow

### Stage 1 → Stage 2

- **Queue:** PostgreSQL `ScanRequestJob` table with `stage='ALIGNMENT'`
- **Data passed:** Metadata only (job row with `qr_data` JSONB column)
- **Images:** Stage 2 fetches scan from S3 using `scan_request.key`

### Stage 2 → Stage 3

- **Queue:** PostgreSQL `ScanRequestJob` table with `stage='DETECTION'`
- **Data passed:** Metadata + `warped_image_key` (S3 path)
- **Images:** Stage 3 fetches warped image from S3

## Database Schema Changes

### ScanRequestJob - New Columns

| Column | Type | Description |
|--------|------|-------------|
| `stage` | ENUM('QR_PREPROCESS', 'ALIGNMENT', 'DETECTION') | Which pipeline stage |
| `exam_paper_id` | UUID (nullable) | Template ID, populated after stage 1 |
| `exam_round_id` | UUID (nullable) | Exam round ID, populated after stage 1 |
| `qr_data` | JSONB (nullable) | QR corners + parsed metadata |
| `warped_image_key` | TEXT (nullable) | S3 path to warped image |

### New Indexes

```sql
-- Stage 1: Pick oldest pending QR_PREPROCESS jobs
CREATE INDEX idx_job_stage1_pick ON "ScanRequestJob"
  (stage, "finishedAt", "startedAt")
  WHERE stage = 'QR_PREPROCESS';

-- Stage 2: Pick ALIGNMENT jobs grouped by template
CREATE INDEX idx_job_stage2_pick ON "ScanRequestJob"
  (stage, "finishedAt", "examPaperId", "startedAt")
  WHERE stage = 'ALIGNMENT';

-- Stage 3: Pick oldest pending DETECTION jobs
CREATE INDEX idx_job_stage3_pick ON "ScanRequestJob"
  (stage, "finishedAt", "startedAt")
  WHERE stage = 'DETECTION';
```

### Job Lifecycle (DAG Model)

```
ScanRequest (id=1)
├── ScanRequestJob (stage=QR_PREPROCESS, result=FAILED)      ← attempt 1
├── ScanRequestJob (stage=QR_PREPROCESS, result=SUCCESS)     ← attempt 2 (retry)
├── ScanRequestJob (stage=ALIGNMENT, result=SUCCESS)
├── ScanRequestJob (stage=DETECTION, result=FAILED)          ← attempt 1
└── ScanRequestJob (stage=DETECTION, result=SUCCESS)         ← attempt 2 (retry)
```

**Rules:**

- A stage can start only if previous stage has a SUCCESS job
- Multiple jobs per stage allowed (retries)
- Only one active (unfinished) job per stage at a time
- Dependency checked via query, not explicit FK links

## Worker Implementations

### Stage 1: QR Preprocess Worker

**Docker tag:** `latest-preprocess` / `develop-preprocess`
**Instance type:** CPU-only (cheap)
**Dependencies:** OpenCV, zxingcpp (no torch)

```python
async def start(self):
    while not self._shutdown_requested:
        # 1. Pick pending ScanRequest (no existing QR_PREPROCESS job)
        scan_request = await self._pick_scan_request()
        if not scan_request:
            await asyncio.sleep(5)
            continue

        # 2. Create QR_PREPROCESS job
        job = await self._create_job(scan_request.id, stage='QR_PREPROCESS')

        try:
            # 3. Download image from S3
            image = await self._download_image(scan_request.key)

            # 4. Detect QR codes, parse metadata
            qr_data = self._detect_and_parse_qr(image)
            # qr_data = {exam_round_id, exam_paper_id, area_id, qr_corners}

            # 5. Mark job SUCCESS, store qr_data
            await self._complete_job(job.id, qr_data=qr_data)

            # 6. Create ALIGNMENT job for next stage
            await self._create_job(
                scan_request.id,
                stage='ALIGNMENT',
                exam_paper_id=qr_data['exam_paper_id'],
                qr_data=qr_data
            )
        except ProcessError as e:
            await self._fail_job(job.id, error=e)
```

### Stage 2: Alignment Worker

**Docker tag:** `latest` / `develop`
**Instance type:** GPU
**Dependencies:** torch, romav2, OpenCV

```python
class AlignmentWorker:
    BATCH_SIZE = 8          # Max scans per batch
    MAX_WAIT_SECONDS = 10   # No job waits longer than this

    async def start(self):
        while not self._shutdown_requested:
            # 1. Pick a batch (same template, respecting timeout)
            jobs = await self._pick_alignment_batch()
            if not jobs:
                await asyncio.sleep(1)
                continue

            exam_paper_id = jobs[0].exam_paper_id

            try:
                # 2. Load template ONCE for entire batch
                template = await self._load_template(exam_paper_id)

                # 3. Download all scan images in parallel
                images = await asyncio.gather(*[
                    self._download_image(job.scan_request.key)
                    for job in jobs
                ])

                # 4. Batch inference through RoMaV2
                warped_images = self._batch_align(images, template, jobs)

                # 5. Upload warped images to S3 in parallel
                warped_keys = await asyncio.gather(*[
                    self._upload_warped(job.id, warped)
                    for job, warped in zip(jobs, warped_images)
                ])

                # 6. Mark jobs SUCCESS, create DETECTION jobs
                for job, warped_key in zip(jobs, warped_keys):
                    await self._complete_job(job.id, warped_image_key=warped_key)
                    await self._create_job(
                        job.scan_request_id,
                        stage='DETECTION',
                        exam_paper_id=exam_paper_id,
                        qr_data=job.qr_data,
                        warped_image_key=warped_key
                    )

            except Exception as e:
                # Fail all jobs in batch
                for job in jobs:
                    await self._fail_job(job.id, error=e)
```

#### Batching Query

```sql
WITH oldest_template AS (
    -- Priority: any job waiting too long
    SELECT "examPaperId"
    FROM "ScanRequestJob"
    WHERE stage = 'ALIGNMENT'
      AND "finishedAt" IS NULL
      AND "startedAt" < NOW() - INTERVAL ':timeout seconds'
    ORDER BY "startedAt"
    LIMIT 1
),
target_template AS (
    SELECT COALESCE(
        (SELECT "examPaperId" FROM oldest_template),
        -- Fallback: template with most pending jobs
        (SELECT "examPaperId"
         FROM "ScanRequestJob"
         WHERE stage = 'ALIGNMENT' AND "finishedAt" IS NULL
         GROUP BY "examPaperId"
         ORDER BY COUNT(*) DESC
         LIMIT 1)
    ) AS "examPaperId"
)
SELECT j.*
FROM "ScanRequestJob" j, target_template t
WHERE j.stage = 'ALIGNMENT'
  AND j."finishedAt" IS NULL
  AND j."examPaperId" = t."examPaperId"
ORDER BY j."startedAt"
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
```

**Batching strategy:**

1. If any job waited > MAX_WAIT_SECONDS → process that template (timeout priority)
2. Otherwise → process template with most pending jobs (batch efficiency)
3. Pick up to BATCH_SIZE jobs for chosen template
4. `FOR UPDATE SKIP LOCKED` prevents conflicts between GPU workers

### Stage 3: Detection Worker

**Docker tag:** `latest-postprocess` / `develop-postprocess`
**Instance type:** CPU-only (cheap)
**Dependencies:** OpenCV (no torch)

```python
class DetectionWorker:
    async def start(self):
        while not self._shutdown_requested:
            # 1. Pick pending DETECTION job
            job = await self._pick_detection_job()
            if not job:
                await asyncio.sleep(5)
                continue

            try:
                # 2. Download warped image from S3
                warped_image = await self._download_image(job.warped_image_key)

                # 3. Load exam configuration (areas, problems)
                exam_config = await self._load_exam_config(
                    job.qr_data['exam_round_id'],
                    job.qr_data['exam_paper_id']
                )

                # 4. Binarize image
                params = self._parse_processing_params(job.scan_request.metadata_)
                warped_thresh = self._binarize_document(warped_image, params)

                # 5. Process areas (reuse ProcessorV1 logic)
                student_info_results = self._process_child_areas(
                    warped_thresh, exam_config.identifier_areas, ...
                )
                problem_results = self._process_child_areas(
                    warped_thresh, exam_config.problem_areas, ...
                )
                option_results = self._process_child_areas(
                    warped_thresh, exam_config.option_areas, ...
                )

                # 6. Derive student ID, calculate score
                student_id = await self._derive_student_id(student_info_results, ...)
                score = self._calculate_score(problem_results, exam_config.problem_map)

                # 7. Create submission (reuse scan.py logic)
                await self._create_submission(
                    job, exam_config, student_id, score,
                    problem_results, student_info_results
                )

                # 8. Upload result images to S3
                await self._upload_results(job, warped_image, warped_thresh, ...)

                # 9. Mark job SUCCESS, update ScanRequest
                await self._complete_job(job.id)
                await self._mark_scan_request_success(job.scan_request_id)

            except ProcessError as e:
                await self._fail_job(job.id, error=e)
```

## Deployment

### Docker Image Tags

| Stage | Image Tag | Base | Size |
|-------|-----------|------|------|
| 1 - QR Preprocess | `latest-preprocess` | python:slim | ~500MB |
| 2 - Alignment | `latest` | nvidia/cuda | ~8GB |
| 3 - Detection | `latest-postprocess` | python:slim | ~500MB |

### Multi-stage Dockerfile Strategy

```dockerfile
# Base stage with common dependencies
FROM python:3.12-slim AS base
# Install common deps: SQLAlchemy, aioboto3, etc.

# Preprocess stage (CPU only)
FROM base AS preprocess
# Add: opencv-python-headless, zxingcpp

# Alignment stage (GPU)
FROM nvidia/cuda:12.1-runtime AS alignment
# Add: torch, romav2, opencv

# Postprocess stage (CPU only)
FROM base AS postprocess
# Add: opencv-python-headless
```

### Scaling Strategy

| Stage | Scaling | Reason |
|-------|---------|--------|
| 1 - QR Preprocess | Horizontal (N instances) | CPU-bound, cheap |
| 2 - Alignment | Vertical (bigger GPU) + Horizontal | GPU-bound, expensive |
| 3 - Detection | Horizontal (N instances) | CPU-bound, cheap |

## Configuration

### Environment Variables

```bash
# Stage selection
WORKER_STAGE=qr_preprocess|alignment|detection

# Stage 2 specific
ALIGNMENT_BATCH_SIZE=8
ALIGNMENT_MAX_WAIT_SECONDS=10
```

## Error Handling

### Stage Failures

| Failure | Behavior |
|---------|----------|
| Stage 1 fails | ScanRequest can be retried (picked_times incremented) |
| Stage 2 fails | All jobs in batch marked FAILED, individual retry possible |
| Stage 3 fails | Job marked FAILED, retry creates new DETECTION job |

### Stale Job Detection

Existing heartbeat mechanism applies per-job. Each stage worker updates `heartbeat_at` during processing.

## Migration Plan

1. **Phase 1:** Add new columns to ScanRequestJob (backward compatible)
2. **Phase 2:** Deploy Stage 1 worker alongside existing worker
3. **Phase 3:** Deploy Stage 2 and 3 workers
4. **Phase 4:** Route new ScanRequests to pipeline
5. **Phase 5:** Deprecate monolithic worker

## Open Questions

1. **Retry policy:** Should each stage have independent retry limits?
2. **Monitoring:** How to track end-to-end latency across stages?
3. **Backpressure:** What if Stage 2 can't keep up with Stage 1?

## Appendix: RoMaV2 Batch Inference

The model supports batch dimension (confirmed in `vendor/romav2/tests/test_fps.py`):

```python
# Batch inference: same template, multiple scans
img_template = load_template(...)  # (1, C, H, W)
img_scans = stack([scan1, scan2, ...])  # (B, C, H, W)

# Expand template to match batch size
img_template_batched = img_template.expand(B, -1, -1, -1)

# Single forward pass for entire batch
preds = model(img_template_batched, img_scans)
```

This requires extending `DocumentMatcher.match()` to support batch inputs.
