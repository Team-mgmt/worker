# Scan artifact storage

The worker can retain evaluation artifacts for `/inference/analyze_vision` in a private S3 bucket.
Storage is disabled by default so placeholder backend S3 settings never break inference.

## Object layout

```text
shelfalign/scans/{libraryCode}/{yyyy}/{mm}/{dd}/{runId}/
  original.jpg
  annotated.jpg
  result.json
  crops/
    001.jpg
    002.jpg
  ground-truth.json  # reserved for reviewed labels; not created automatically
```

`result.json` includes the detector SHA-256, OCR and matching output, bounding boxes,
candidate scores, decisions, and stage timings. Metrics such as mAP and OCR CER require a
reviewed `ground-truth.json`; predictions alone are not ground truth.

## Worker configuration

Set these values in `/opt/shelfalign/.env`:

```dotenv
AWS_REGION=ap-northeast-2
S3_BUCKET_NAME=your-private-scan-artifact-bucket
SCAN_ARTIFACTS_ENABLED=true
SCAN_ARTIFACTS_PREFIX=shelfalign/scans
SCAN_ARTIFACTS_SAVE_CROPS=true
```

Use an EC2 IAM role instead of putting AWS access keys in `.env`. The worker needs this minimum
permission, with the bucket name replaced:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::your-private-scan-artifact-bucket/shelfalign/scans/*"
    }
  ]
}
```

Keep Block Public Access enabled. Add an S3 Lifecycle rule to expire development scans or move
older artifacts to an archive class. S3 failures are logged but do not fail the inference response.
