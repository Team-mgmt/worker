from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import aioboto3
from PIL import Image, ImageDraw, ImageFont

from worker.core.config import settings
from worker.schemas.inference import MatchResponse


SAFE_KEY_PART = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_key_part(value: str) -> str:
    return SAFE_KEY_PART.sub("-", value.strip()).strip("-._") or "unknown"


@lru_cache(maxsize=8)
def _file_sha256_cached(path: str, size: int, modified_ns: int) -> str:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: str) -> str | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    stat = file_path.stat()
    return _file_sha256_cached(path, stat.st_size, stat.st_mtime_ns)


class ScanArtifactService:
    @property
    def enabled(self) -> bool:
        return settings.SCAN_ARTIFACTS_ENABLED and bool(settings.S3_BUCKET_NAME)

    def build_prefix(self, library_code: str, run_id: str, created_at: datetime) -> str:
        root = settings.SCAN_ARTIFACTS_PREFIX.strip("/")
        return "/".join(
            (
                root,
                safe_key_part(library_code),
                created_at.strftime("%Y/%m/%d"),
                safe_key_part(run_id),
            )
        )

    async def save_scan(
        self,
        *,
        run_id: str,
        image_path: Path,
        library_code: str,
        room_name: str | None,
        response: MatchResponse,
        timings: dict[str, float],
        model_path: str | None,
    ) -> str | None:
        if not self.enabled:
            return None

        created_at = datetime.now(UTC)
        prefix = self.build_prefix(library_code, run_id, created_at)
        original_suffix = image_path.suffix.lower() if image_path.suffix else ".jpg"
        original_key = f"{prefix}/original{original_suffix}"
        annotated_key = f"{prefix}/annotated.jpg"

        with Image.open(image_path) as source:
            image = source.convert("RGB")

        session = aioboto3.Session()
        async with session.client("s3", region_name=settings.AWS_REGION) as client:
            await self._put_bytes(client, original_key, image_path.read_bytes(), self._content_type(original_suffix))
            await self._put_image(client, annotated_key, self._annotate(image, response))

            crop_keys: dict[int, str] = {}
            if settings.SCAN_ARTIFACTS_SAVE_CROPS:
                for result in response.results:
                    crop = self._crop(image, result.bbox)
                    if crop is None:
                        continue
                    crop_key = f"{prefix}/crops/{result.detected_order:03d}.jpg"
                    await self._put_image(client, crop_key, crop)
                    crop_keys[result.detected_order] = crop_key

            result_payload: dict[str, Any] = {
                "schema_version": "1.0",
                "run_id": run_id,
                "created_at": created_at.isoformat(),
                "library": {"code": library_code, "room_name": room_name},
                "artifacts": {
                    "original_key": original_key,
                    "annotated_key": annotated_key,
                    "crop_keys": {str(order): key for order, key in crop_keys.items()},
                    "ground_truth_key": f"{prefix}/ground-truth.json",
                },
                "model": {
                    "detector_path": model_path,
                    "detector_sha256": file_sha256(model_path) if model_path else None,
                    "ocr": "PaddleOCR",
                },
                "timings_seconds": timings,
                "inference": response.model_dump(mode="json", exclude={"artifact_run_id", "artifact_prefix"}),
            }
            await self._put_bytes(
                client,
                f"{prefix}/result.json",
                json.dumps(result_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        return prefix

    async def _put_bytes(self, client: Any, key: str, body: bytes, content_type: str) -> None:
        await client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def _put_image(self, client: Any, key: str, image: Image.Image) -> None:
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        await self._put_bytes(client, key, output.getvalue(), "image/jpeg")

    @staticmethod
    def _content_type(suffix: str) -> str:
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")

    @staticmethod
    def _crop(image: Image.Image, bbox: list[float] | None) -> Image.Image | None:
        if not bbox or len(bbox) != 4:
            return None
        left, top, right, bottom = bbox
        box = (
            max(0, round(left)),
            max(0, round(top)),
            min(image.width, round(right)),
            min(image.height, round(bottom)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        return image.crop(box)

    @staticmethod
    def _annotate(image: Image.Image, response: MatchResponse) -> Image.Image:
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        font = ImageFont.load_default()
        colors = {
            "normal": "#16a34a",
            "suspected_misplacement": "#dc2626",
            "needs_review": "#f59e0b",
            "unmatched": "#71717a",
        }
        width = max(2, round(min(image.size) / 300))
        for result in response.results:
            if not result.bbox or len(result.bbox) != 4:
                continue
            color = colors.get(result.decision, "#71717a")
            box = tuple(round(value) for value in result.bbox)
            draw.rectangle(box, outline=color, width=width)
            label = f"{result.detected_order} {result.decision} {result.match_score or 0:.1f}"
            text_box = draw.textbbox((box[0], box[1]), label, font=font)
            draw.rectangle(text_box, fill=color)
            draw.text((box[0], box[1]), label, fill="white", font=font)
        return annotated


scan_artifact_service = ScanArtifactService()
