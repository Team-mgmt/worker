"""Sync per-bubble debug data into the Label Studio bucket as labeling tasks.

Reads each job's ``bubble_decisions/<kind>.json`` under
``s3://<source-bucket>/<source-prefix>/<request_id>/<job_id>/``, copies the
matching ``bubbles/<kind>/<area_key>__{scan,template}.png`` crops to the
Label Studio bucket, and writes one task JSON per bubble at
``s3://<dest-bucket>/<dest-prefix>/tasks/<request_id>/<job_id>/<kind>/<area_key>.json``.

Label Studio is configured with an S3 source storage pointing at the
``tasks/`` prefix with ``use_blob_urls=False`` so each JSON becomes one task,
and ``presign=True`` so the ``s3://`` URIs inside each task data dict get
presigned at view time.

Run with ``--dry-run`` first to see the plan. ``boto3`` is available
transitively via ``aioboto3``; if it ever stops being so, add it explicitly
with ``uv add boto3``.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError


SOURCE_BUCKET_DEFAULT = "dev-qmr-assets"
SOURCE_PREFIX_DEFAULT = "qmr-worker/debug"
DEST_BUCKET_DEFAULT = "dev-hi4labs-label-studio"
DEST_PREFIX_DEFAULT = "qmr-worker"
KINDS_DEFAULT = ("option", "problem", "identifier", "metadata")


class _StrictModel(BaseModel):
    """Strict-by-default base — reject coerced ints/strings/booleans.

    debug_dump.py emits Python-native floats/ints/bools via ``np.scalar.item()``,
    so strict mode round-trips legitimate payloads cleanly while rejecting
    type-coerced ones (per AGENTS.md guidance on schema parsing).
    """

    model_config = ConfigDict(strict=True)


class Crop(_StrictModel):
    x0: int
    y0: int
    x1: int
    y1: int


class Metrics(_StrictModel):
    version: int
    is_filled: bool
    fill_ratio: float | None = None
    baseline_fill_ratio: float | None = None
    delta_fill_ratio: float | None = None


class Thresholds(_StrictModel):
    fill_ratio_threshold: float
    delta_fill_ratio_threshold: float
    absolute_fill_ratio_threshold: float | None = None
    use_template_baseline_fill_delta: bool


class BubbleDecision(_StrictModel):
    """One entry in ``bubble_decisions/<kind>.json`` (debug_dump.py:238)."""

    area_id: str
    area_index: int
    local_id: str
    crop: Crop
    metrics: Metrics
    baseline_fill_ratio_input: float | None = None
    thresholds: Thresholds


class DecisionsFile(_StrictModel):
    """Whole-file wrapper so pydantic gives us all-or-nothing semantics."""

    decisions: list[BubbleDecision] = Field(default_factory=list)


@dataclass(frozen=True)
class JobLocator:
    request_id: str
    job_id: str

    @property
    def relpath(self) -> str:
        return f"{self.request_id}/{self.job_id}"


def list_jobs(s3, bucket: str, prefix: str) -> list[JobLocator]:
    paginator = s3.get_paginator("list_objects_v2")
    seen: set[tuple[str, str]] = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix.rstrip('/')}/"):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            rest = key[len(prefix.rstrip("/")) + 1 :]
            parts = rest.split("/", 2)
            if len(parts) >= 2:
                seen.add((parts[0], parts[1]))
    return [JobLocator(req, job) for req, job in sorted(seen)]


def load_decisions(s3, bucket: str, key: str) -> list[BubbleDecision]:
    """Read and validate a ``bubble_decisions/<kind>.json`` file.

    All-or-nothing: a single malformed entry rejects the file (matches the
    AGENTS.md guidance to let pydantic drive the fallback branch).
    """
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return []
        raise
    try:
        return DecisionsFile.model_validate({"decisions": json.loads(body)}).decisions
    except json.JSONDecodeError as e:
        print(f"[skip] {key}: invalid JSON ({e.msg} at offset {e.pos})", file=sys.stderr)
        return []
    except ValidationError as e:
        print(f"[skip] {key}: validation failed ({e.error_count()} errors)", file=sys.stderr)
        return []


def build_task(
    *,
    decision: BubbleDecision,
    job: JobLocator,
    kind: str,
    dest_bucket: str,
    dest_prefix: str,
) -> dict:
    """Build a Label Studio task JSON for one bubble."""
    area_key = f"{decision.area_id}_{decision.local_id}"
    bubbles_prefix = f"{dest_prefix}/debug/{job.relpath}/bubbles/{kind}"
    scan_uri = f"s3://{dest_bucket}/{bubbles_prefix}/{area_key}__scan.png"
    template_uri = f"s3://{dest_bucket}/{bubbles_prefix}/{area_key}__template.png"
    metrics = decision.metrics
    worker_verdict = "filled" if metrics.is_filled else "not-filled"

    # Preserve valid 0.0 measurements; `x or y` would treat them as falsey.
    if metrics.delta_fill_ratio is not None:
        score = metrics.delta_fill_ratio
    elif metrics.fill_ratio is not None:
        score = metrics.fill_ratio
    else:
        score = 0.0

    return {
        "data": {
            "scan": scan_uri,
            "template": template_uri,
            "worker_verdict": worker_verdict,
            "fill_ratio": metrics.fill_ratio,
            "baseline_fill_ratio": metrics.baseline_fill_ratio,
            "delta_fill_ratio": metrics.delta_fill_ratio,
            "kind": kind,
            "area_id": decision.area_id,
            "area_index": decision.area_index,
            "local_id": decision.local_id,
            "request_id": job.request_id,
            "job_id": job.job_id,
            "crop": decision.crop.model_dump(),
            "thresholds": decision.thresholds.model_dump(),
        },
        "predictions": [
            {
                "model_version": f"qmr-worker.v{metrics.version}",
                "score": score,
                "result": [
                    {
                        "from_name": "verdict",
                        "to_name": "scan",
                        "type": "choices",
                        "value": {"choices": [worker_verdict]},
                    }
                ],
            }
        ],
    }


def copy_object(s3, *, source_bucket: str, source_key: str, dest_bucket: str, dest_key: str) -> None:
    s3.copy_object(
        Bucket=dest_bucket,
        Key=dest_key,
        CopySource={"Bucket": source_bucket, "Key": source_key},
        MetadataDirective="COPY",
    )


def put_json(s3, *, bucket: str, key: str, body: dict) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def sync_bubble(
    s3,
    *,
    source_bucket: str,
    dest_bucket: str,
    src_scan_key: str,
    dst_scan_key: str,
    src_template_key: str,
    dst_template_key: str,
    task_key: str,
    task: dict,
) -> None:
    # Copies must succeed before the task JSON lands; otherwise Label Studio
    # gets a task that references non-existent scan/template objects.
    copy_object(
        s3,
        source_bucket=source_bucket,
        source_key=src_scan_key,
        dest_bucket=dest_bucket,
        dest_key=dst_scan_key,
    )
    copy_object(
        s3,
        source_bucket=source_bucket,
        source_key=src_template_key,
        dest_bucket=dest_bucket,
        dest_key=dst_template_key,
    )
    put_json(s3, bucket=dest_bucket, key=task_key, body=task)


_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_FORBIDDEN_CODES = frozenset({"403", "AccessDenied", "Forbidden"})


def probe_head_treats_missing_as_403(s3, *, bucket: str, prefix: str) -> bool:
    """Return True iff the caller's IAM makes 404 indistinguishable from 403.

    S3 returns 403 (not 404) for a missing key when the caller lacks
    ``s3:ListBucket``. Probing a guaranteed-absent key tells us which response
    the bucket+caller produce so ``head_exists`` can interpret 403 correctly
    instead of guessing.
    """
    probe_key = f"{prefix.rstrip('/')}/.head-probe-{uuid.uuid4().hex}"
    try:
        s3.head_object(Bucket=bucket, Key=probe_key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in _FORBIDDEN_CODES:
            return True
        if code in _MISSING_CODES:
            return False
        raise
    return False  # probe collided with an actual key; treat as normal 404 mode


def head_exists(s3, *, bucket: str, key: str, treat_403_as_missing: bool) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in _MISSING_CODES:
            return False
        if treat_403_as_missing and code in _FORBIDDEN_CODES:
            return False
        raise


def plan_and_apply(
    *,
    s3,
    jobs: Iterable[JobLocator],
    kinds: Iterable[str],
    source_bucket: str,
    source_prefix: str,
    dest_bucket: str,
    dest_prefix: str,
    limit: int | None,
    dry_run: bool,
    workers: int,
    overwrite_tasks: bool,
) -> int:
    """Run the sync and return the total number of per-bubble failures."""
    pool = ThreadPoolExecutor(max_workers=workers)
    n_tasks = n_copies = total_errors = 0
    treat_403_as_missing = probe_head_treats_missing_as_403(
        s3, bucket=dest_bucket, prefix=dest_prefix
    )
    if treat_403_as_missing:
        print(
            f"[info] caller lacks s3:ListBucket on {dest_bucket}; "
            "treating 403 HEAD responses as missing.",
            file=sys.stderr,
        )

    for job in jobs:
        for kind in kinds:
            decisions_key = f"{source_prefix.rstrip('/')}/{job.relpath}/bubble_decisions/{kind}.json"
            decisions = load_decisions(s3, source_bucket, decisions_key)
            if not decisions:
                continue
            futs = []
            bubbles_planned = 0
            for d in decisions:
                if limit is not None and n_tasks >= limit:
                    break
                area_key = f"{d.area_id}_{d.local_id}"
                task_key = f"{dest_prefix.rstrip('/')}/tasks/{job.relpath}/{kind}/{area_key}.json"

                # Run the existing-task check before counters so already-synced
                # bubbles don't consume --limit on reruns.
                if not overwrite_tasks and head_exists(
                    s3,
                    bucket=dest_bucket,
                    key=task_key,
                    treat_403_as_missing=treat_403_as_missing,
                ):
                    continue

                n_tasks += 1
                bubbles_planned += 1
                n_copies += 2
                if dry_run:
                    continue

                task = build_task(
                    decision=d,
                    job=job,
                    kind=kind,
                    dest_bucket=dest_bucket,
                    dest_prefix=dest_prefix,
                )
                bubbles_kind_prefix = f"bubbles/{kind}/{area_key}"
                src_scan_key = f"{source_prefix.rstrip('/')}/{job.relpath}/{bubbles_kind_prefix}__scan.png"
                src_template_key = f"{source_prefix.rstrip('/')}/{job.relpath}/{bubbles_kind_prefix}__template.png"
                dst_scan_key = f"{dest_prefix.rstrip('/')}/debug/{job.relpath}/{bubbles_kind_prefix}__scan.png"
                dst_template_key = f"{dest_prefix.rstrip('/')}/debug/{job.relpath}/{bubbles_kind_prefix}__template.png"
                futs.append(
                    pool.submit(
                        sync_bubble,
                        s3,
                        source_bucket=source_bucket,
                        dest_bucket=dest_bucket,
                        src_scan_key=src_scan_key,
                        dst_scan_key=dst_scan_key,
                        src_template_key=src_template_key,
                        dst_template_key=dst_template_key,
                        task_key=task_key,
                        task=task,
                    )
                )

            errors = 0
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"[error] {e}", file=sys.stderr)
            total_errors += errors
            print(
                f"[{'plan' if dry_run else 'done'}] {job.relpath} / {kind}: "
                f"{bubbles_planned} bubbles -> {bubbles_planned * 2} png + {bubbles_planned} task json "
                + (f"({errors} errors)" if errors else "")
            )

            if limit is not None and n_tasks >= limit:
                pool.shutdown(wait=True)
                print(f"\nReached --limit {limit}; stopping.", file=sys.stderr)
                print(
                    f"Total: {n_tasks} tasks, {n_copies} png copies, {total_errors} errors",
                    file=sys.stderr,
                )
                return total_errors

    pool.shutdown(wait=True)
    print(f"\nTotal: {n_tasks} tasks, {n_copies} png copies, {total_errors} errors")
    return total_errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", default="qmr", help="AWS_PROFILE to use (default: qmr)")
    p.add_argument("--region", default="ap-northeast-2")
    p.add_argument("--source-bucket", default=SOURCE_BUCKET_DEFAULT)
    p.add_argument("--source-prefix", default=SOURCE_PREFIX_DEFAULT)
    p.add_argument("--dest-bucket", default=DEST_BUCKET_DEFAULT)
    p.add_argument(
        "--dest-prefix",
        default=DEST_PREFIX_DEFAULT,
        help="Root prefix inside dest bucket. Writes debug/ and tasks/ under here.",
    )
    p.add_argument(
        "--kinds",
        nargs="+",
        default=list(KINDS_DEFAULT),
        help="Bubble kinds to import",
    )
    p.add_argument("--limit", type=int, default=None, help="Cap total tasks (for sampling runs)")
    p.add_argument(
        "--overwrite-tasks",
        action="store_true",
        help="Re-write task JSONs even if they already exist (default: skip existing)",
    )
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")

    jobs = list_jobs(s3, args.source_bucket, args.source_prefix)
    print(f"Found {len(jobs)} jobs under s3://{args.source_bucket}/{args.source_prefix}/")

    errors = plan_and_apply(
        s3=s3,
        jobs=jobs,
        kinds=args.kinds,
        source_bucket=args.source_bucket,
        source_prefix=args.source_prefix,
        dest_bucket=args.dest_bucket,
        dest_prefix=args.dest_prefix,
        limit=args.limit,
        dry_run=args.dry_run,
        workers=args.workers,
        overwrite_tasks=args.overwrite_tasks,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
