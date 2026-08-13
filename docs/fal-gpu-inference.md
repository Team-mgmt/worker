# fal.ai GPU inference

ShelfAlign can offload YOLO OBB detection and PaddleOCR to fal Serverless while keeping the public FastAPI API, RDS matching, decisions, and S3 artifact storage on AWS.

## Deploy

Use Python 3.12, matching this repository, and authenticate the fal CLI locally. The application is private by default.

```bash
python -m pip install fal
fal auth login
fal deploy fal_app.py::ShelfAlignVision --app-name shelfalign-vision
```

Copy the endpoint ID printed by fal, for example `account/shelfalign-vision`, into the EC2 worker environment:

```env
FAL_KEY=...
FAL_VISION_ENDPOINT=account/shelfalign-vision
FAL_VISION_ENABLED=true
FAL_VISION_TIMEOUT_SECONDS=90
FAL_VISION_FALLBACK_LOCAL=true
```

Restart the worker after editing `/opt/shelfalign/.env`:

```bash
sudo systemctl restart shelfalign-worker.service
sudo journalctl -u shelfalign-worker.service -f --no-pager -o cat
```

Keep `min_concurrency=0` and `max_concurrency=1` during evaluation to cap cost. The runner keeps warm for 20 seconds. Compare the same fixed image set before and after enabling fal; record total latency, detection/OCR latency, target Top-1 accuracy, and the fal App Analytics cost. Do not enable fal in production until the remote Paddle GPU image has passed this comparison.
