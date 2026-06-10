"""Extract a smoke-test fixture from the dev environment.

Captures one real ``ScanRequest`` and everything needed to replay the
post-alignment half of ``ProcessorV1.process`` against it offline — no
S3, no DB, no GPU:

  - the original scan image (for QR decoding)
  - the exam paper template (PNG/JPG/SVG)
  - the post-RoMaV2 warped scan (``warped.png``), so the test can patch
    ``_align_scan_to_template`` and skip the deep-learning aligner
  - the threshold image, plus result JSONs (``results.json``,
    ``area_metrics.json``, ``annotations_cropped.json``) for assertions
  - the ScanLogs row sequence from the production run (for debugging)
  - the DB rows ProcessorV1 reads (Exam, ExamPaper, areas, area types)

Usage:
    AWS_PROFILE=shelfalign uv run python scripts/extract_smoke_fixture.py <scan-request-id>

Requires ``.claude/scripts/psql-dev.sh`` for DB credentials. Writes to
``tests/fixtures/smoke/<scan-request-id>/``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PSQL_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "psql-dev.sh"
DEFAULT_BUCKET = "dev-shelfalign-assets"

# Result artifacts uploaded by ScanWorker.upload_results() in
# worker/worker/scan.py. Each entry maps S3 basename → local filename.
RESULT_ARTIFACTS = {
    "results.json": "results.json",
    "area_metrics.json": "area_metrics.json",
    "annotations.json": "annotations.json",
    "annotations_cropped.json": "annotations_cropped.json",
    "flattened.png": "warped.png",  # post-alignment image
    "threshold.png": "threshold.png",  # post-alignment + binarization
}


def _database_url() -> str:
    """Read DATABASE_URL out of psql-dev.sh without invoking it."""
    text = PSQL_SCRIPT.read_text()
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("DATABASE_"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"')
    return (
        f"postgresql://{env['DATABASE_USER']}:{env['DATABASE_PASS']}"
        f"@{env['DATABASE_HOST']}:5432/{env['DATABASE_NAME']}"
    )


_DB_URL = _database_url()


def psql_json(query: str) -> list[dict]:
    """Run a SELECT and return JSON-parsed rows via json_agg.

    Uses ``psql -At`` so output is exactly one row of JSON (or empty),
    bypassing the aligned-table formatting that breaks long JSON over
    multiple lines.
    """
    wrapped = f"SELECT json_agg(t) FROM ({query}) t;"
    out = subprocess.check_output(
        ["psql", _DB_URL, "-At", "-c", wrapped], text=True,
    ).strip()
    if not out:
        return []
    return json.loads(out)


def fetch_one(query: str) -> dict:
    rows = psql_json(query)
    if not rows:
        raise SystemExit(f"No row returned for query:\n{query}")
    return rows[0]


def s3_cp(bucket: str, key: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["aws", "s3", "cp", f"s3://{bucket}/{key}", str(dest)],
        env={**os.environ, "AWS_PROFILE": os.environ.get("AWS_PROFILE", "shelfalign")},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scan_request_id", help="UUID of the ScanRequest to capture")
    parser.add_argument(
        "--bucket",
        default=os.environ.get("S3_BUCKET_NAME", DEFAULT_BUCKET),
        help="S3 bucket (default: $S3_BUCKET_NAME or dev-shelfalign-assets)",
    )
    args = parser.parse_args()

    out_dir = REPO_ROOT / "tests" / "fixtures" / "smoke" / args.scan_request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] Fetching ScanRequest {args.scan_request_id}…")
    scan_request = fetch_one(
        f"SELECT * FROM \"ScanRequest\" WHERE id = '{args.scan_request_id}'"
    )
    metadata = scan_request["metadata"]
    if "e" not in metadata or "a" not in metadata:
        raise SystemExit(f"ScanRequest.metadata missing 'e'/'a': {metadata}")

    sys.path.insert(0, str(REPO_ROOT))
    from worker.util import base64url_to_uuid  # noqa: E402

    exam_round_id = str(base64url_to_uuid(metadata["e"]))
    area_id = str(base64url_to_uuid(metadata["a"]))
    print(f"      exam_round_id={exam_round_id}  area_id={area_id}")

    print("[2/6] Fetching ExamRound → Exam → ExamPaper…")
    exam_round = fetch_one(f"SELECT * FROM \"ExamRound\" WHERE id = '{exam_round_id}'")
    exam = fetch_one(f"SELECT * FROM \"Exam\" WHERE id = '{exam_round['examId']}'")
    exam_paper = fetch_one(f"SELECT * FROM \"ExamPaper\" WHERE id = '{exam['examPaperId']}'")
    paper_type = fetch_one(f"SELECT * FROM \"PaperType\" WHERE id = '{exam_paper['paperTypeId']}'")

    print("[3/6] Fetching areas + area types…")
    areas = psql_json(
        f"SELECT * FROM \"ExamPaperArea\" WHERE \"examPaperId\" = '{exam_paper['id']}'"
    )
    area_type_ids = sorted({a["areaTypeId"] for a in areas})
    area_types_pred = ",".join(f"'{aid}'" for aid in area_type_ids)
    area_types = psql_json(
        f"SELECT * FROM \"ExamPaperAreaType\" WHERE id IN ({area_types_pred})"
    )
    print(f"      {len(areas)} areas, {len(area_types)} area types")

    print("[4/6] Locating most recent successful ScanRequestJob…")
    job = fetch_one(
        f"SELECT * FROM \"ScanRequestJob\" "
        f"WHERE \"scanRequestId\" = '{args.scan_request_id}' AND result = 'SUCCESS' "
        f"ORDER BY \"finishedAt\" DESC LIMIT 1"
    )
    job_id = job["id"]
    job_org_id = job["organizationId"] or exam["organizationId"]
    print(f"      job_id={job_id}  finishedAt={job['finishedAt']}")

    print("[4b] Fetching ScanLogs…")
    scan_logs = psql_json(
        f"SELECT \"logLevel\", message, \"createdAt\" FROM \"ScanLogs\" "
        f"WHERE \"jobId\" = '{job_id}' ORDER BY \"createdAt\" ASC"
    )
    print(f"      {len(scan_logs)} log lines")

    print("[5/6] Downloading scan + template…")
    scan_key = scan_request["key"]
    scan_ext = Path(scan_key).suffix or ".jpg"
    s3_cp(args.bucket, scan_key, out_dir / f"scan{scan_ext}")
    bg_key = exam_paper["backgroundImage"]
    bg_ext = Path(bg_key).suffix or ""
    s3_cp(args.bucket, bg_key, out_dir / f"template{bg_ext}")

    print("[6/6] Downloading result artifacts (warped image + golden JSONs)…")
    result_base = f"{job_org_id}/scans/{args.scan_request_id}/{job_id}"
    captured_artifacts: dict[str, str] = {}
    for s3_name, local_name in RESULT_ARTIFACTS.items():
        s3_cp(args.bucket, f"{result_base}/{s3_name}", out_dir / local_name)
        captured_artifacts[s3_name] = local_name

    fixture = {
        "scan_request": {
            "id": scan_request["id"],
            "key": scan_request["key"],
            "metadata": scan_request["metadata"],
            "organization_id": scan_request["organizationId"],
            "source": scan_request["source"],
        },
        "qr": {"exam_round_id": exam_round_id, "area_id": area_id},
        "exam_round": exam_round,
        "exam": exam,
        "exam_paper": exam_paper,
        "paper_type": paper_type,
        "areas": areas,
        "area_types": area_types,
        "job": {
            "id": job_id,
            "organization_id": job_org_id,
            "started_at": job["startedAt"],
            "finished_at": job["finishedAt"],
            "result": job["result"],
            "result_code": job["resultCode"],
        },
        "scan_logs": scan_logs,
        "image_files": {
            "scan": f"scan{scan_ext}",
            "template": f"template{bg_ext}",
            "warped": "warped.png",
            "threshold": "threshold.png",
        },
        "result_files": {
            "results": "results.json",
            "area_metrics": "area_metrics.json",
            "annotations": "annotations.json",
            "annotations_cropped": "annotations_cropped.json",
        },
    }
    fixture_path = out_dir / "fixture.json"
    with fixture_path.open("w", encoding="utf-8") as fp:
        json.dump(fixture, fp, indent=2, ensure_ascii=False, default=str)

    print(f"\nDone → {out_dir.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
