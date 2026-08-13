from __future__ import annotations

import os
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from worker.core.config import settings
from worker.schemas.inference import OCRResultItem


class RemoteVisionError(RuntimeError):
    """Raised when fal vision inference cannot produce a valid result."""


class RemoteVisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_order: int = Field(ge=1)
    raw_text: str = ""
    title: str | None = None
    author: str | None = None
    call_number: str | None = None
    bbox: list[float] = Field(min_length=4, max_length=4)
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    detection_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    obb_polygon: list[list[float]] | None = None
    crop_method: str | None = None
    crop_size: list[int] | None = None
    ocr_variant: str | None = None
    ocr_attempt_count: int | None = Field(default=None, ge=1)
    ocr_label_text: str | None = None
    ocr_label_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RemoteVisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RemoteVisionItem]
    detection_seconds: float = Field(ge=0.0)
    ocr_seconds: float = Field(ge=0.0)
    model_sha256: str


class FalVisionService:
    @property
    def enabled(self) -> bool:
        return settings.FAL_VISION_ENABLED

    async def analyze(self, image_path: Path, *, adaptive: bool) -> tuple[list[OCRResultItem], float, float, str]:
        if not settings.FAL_VISION_ENDPOINT.strip():
            raise RemoteVisionError("FAL_VISION_ENDPOINT is empty.")
        if not os.getenv("FAL_KEY"):
            raise RemoteVisionError("FAL_KEY is not configured.")

        try:
            import fal_client
        except ImportError as exc:
            raise RemoteVisionError("fal-client is not installed.") from exc

        started_at = time.perf_counter()
        try:
            client = fal_client.AsyncClient(default_timeout=float(settings.FAL_VISION_TIMEOUT_SECONDS))
            image_url = await client.upload_file(image_path, repository="fal_v3")
            payload = await client.subscribe(
                settings.FAL_VISION_ENDPOINT,
                arguments={"image_url": image_url, "adaptive": adaptive},
                client_timeout=float(settings.FAL_VISION_TIMEOUT_SECONDS),
            )
            response = RemoteVisionResponse.model_validate(payload)
        except ValidationError as exc:
            raise RemoteVisionError(f"fal returned an invalid response: {exc}") from exc
        except Exception as exc:
            raise RemoteVisionError(f"fal vision request failed after {time.perf_counter() - started_at:.1f}s: {exc}") from exc

        items = [OCRResultItem.model_validate(item.model_dump()) for item in response.items]
        return items, response.detection_seconds, response.ocr_seconds, response.model_sha256


fal_vision_service = FalVisionService()
