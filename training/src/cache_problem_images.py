from __future__ import annotations

import argparse
import csv
import subprocess
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache S3 images referenced by a manifest into a local directory."
    )
    parser.add_argument("--manifest", type=Path, action="append", required=True, help="Manifest CSV path. Can be repeated.")
    parser.add_argument("--cache-dir", type=Path, required=True, help="Local cache root.")
    parser.add_argument("--profile", type=str, default=None, help="Optional AWS CLI profile.")
    parser.add_argument(
        "--include-template",
        action="store_true",
        help="Also download template images. By default only scan images are cached.",
    )
    parser.add_argument(
        "--bucket-override",
        action="append",
        default=[],
        help="Optional bucket rewrite in SOURCE=TARGET form. Can be repeated.",
    )
    return parser.parse_args()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Unsupported URI: {uri}")
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return bucket, key


def rewrite_s3_uri(uri: str, bucket_overrides: dict[str, str]) -> str:
    bucket, key = parse_s3_uri(uri)
    rewritten_bucket = bucket_overrides.get(bucket, bucket)
    return f"s3://{rewritten_bucket}/{key}"


def s3_uri_to_local_path(cache_dir: Path, uri: str) -> Path:
    bucket, key = parse_s3_uri(uri)
    return cache_dir / bucket / Path(key)


def parse_bucket_overrides(raw_overrides: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw_override in raw_overrides:
        source, separator, target = raw_override.partition("=")
        if not separator or not source or not target:
            raise ValueError(f"Invalid --bucket-override value: {raw_override}")
        overrides[source] = target
    return overrides


def run_aws_cp_file(source_uri: str, destination_path: Path, profile: str | None) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "aws",
        "s3",
        "cp",
        source_uri,
        str(destination_path),
    ]
    if profile:
        command.extend(["--profile", profile])
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    bucket_overrides = parse_bucket_overrides(args.bucket_override)

    selected_uris: set[str] = set()

    for manifest_path in args.manifest:
        with manifest_path.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                for column in ("image_uri", "template_uri"):
                    if column == "template_uri" and not args.include_template:
                        continue
                    selected_uris.add(row[column])

    downloaded = 0
    skipped_existing = 0
    for uri in sorted(selected_uris):
        rewritten_uri = rewrite_s3_uri(uri, bucket_overrides)
        destination_path = s3_uri_to_local_path(args.cache_dir, rewritten_uri)
        if destination_path.exists():
            skipped_existing += 1
            continue
        run_aws_cp_file(
            source_uri=rewritten_uri,
            destination_path=destination_path,
            profile=args.profile,
        )
        downloaded += 1

    print(f"unique_uris={len(selected_uris)}")
    print(f"downloaded={downloaded}")
    print(f"skipped_existing={skipped_existing}")
    print(f"manifests={len(args.manifest)}")
    print(f"bucket_overrides={bucket_overrides}")
    print(f"cache_dir={args.cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
