# Modal GPU inference

ShelfAlign offloads YOLO OBB detection and PaddleOCR to a private Modal L4 endpoint. The public FastAPI API, RDS matching, decisions, and S3 artifacts stay on AWS. If Modal fails, the worker uses the existing local CPU path when `REMOTE_VISION_FALLBACK_LOCAL=true`.

## Deploy

Authenticate once on the development PC, then deploy from the repository root:

```cmd
.\.venv\Scripts\python.exe -m modal setup
.\.venv\Scripts\python.exe -m modal deploy modal_app.py
```

The deployment output prints the private `modal.run` endpoint URL. Create a dedicated proxy token for EC2 in the Modal dashboard. Do not reuse or commit a personal token.

Set these values in `/opt/shelfalign/.env`:

```env
REMOTE_VISION_ENABLED=true
REMOTE_VISION_PROVIDER=modal
REMOTE_VISION_ENDPOINT=https://...modal.run
REMOTE_VISION_TIMEOUT_SECONDS=90
REMOTE_VISION_FALLBACK_LOCAL=true
MODAL_TOKEN_ID=wk-...
MODAL_TOKEN_SECRET=ws-...
```

Restart and follow the worker logs:

```bash
sudo systemctl restart shelfalign-worker.service
sudo journalctl -u shelfalign-worker.service -f --no-pager -o cat | \
  grep --line-buffered -Ei 'remote vision|find_target_book|matching|OCR failed'
```

The app uses one L4, scales to zero, caps at one container, and stays warm for 10 minutes after the last request. The Paddle model cache persists in a Modal Volume. Compare the same fixed images before and after enabling Modal. Record total, remote round-trip, detection and OCR latency, target Top-1 accuracy, administrator matching accuracy, and Modal cost. Keep the workspace budget enabled.

### Target-search precision retry

User-mode target search first runs the fast batched OCR pass over every detected spine. If that pass returns `not_found` and the selected catalog holding has a call number, Modal ranks the detected labels by call-number similarity and reruns adaptive OCR on at most three likely spines. The retry uses the existing perspective crop, CLAHE/sharpen and rotation variants; it does not run over the whole shelf. The final title/author/call-number scoring still runs through the same target matcher.

`result.json` records `precision_ocr`, `precision_ocr_count`, the detected spine count, every bbox/OBB polygon, and the retry-selected OCR metadata. A detected count such as 35 for a shelf containing 33 or 34 physical books is not treated as ground truth: it indicates possible over-detection. More importantly, a missed or merged target spine cannot be recovered by OCR, so detection count and polygons must be reviewed against GT independently of target-search success.

## User-mode artifacts

`POST /inference/find_target_book` stores its diagnostics under the same date-partitioned scan prefix when scan artifact storage is enabled:

```text
shelfalign/scans/{library_code}/{year}/{month}/{day}/{run_id}/
```

The run contains the original and annotated images, optional per-spine crops, and `result.json`. User-mode results set `mode` to `target_search`. The `target_search` object contains the selected catalog book, Top-1/Top-2 candidates, every scored detection, and the title/author/call-number component scores. `inference.results` preserves the complete OCR and detection diagnostics so that the existing polygon ground-truth flow remains usable. A failed S3 upload is logged and does not fail the user search response.
