from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from worker.core.config import settings
from worker.schemas.inference import OCRResultItem, TargetBook


class RemoteVisionError(RuntimeError):
    """Raised when remote vision inference cannot produce a valid result."""


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
    precision_retry_orders: list[int] = Field(default_factory=list)
    precision_ocr_seconds: float = Field(default=0.0, ge=0.0)


class RemoteVisionService:
    @property
    def enabled(self) -> bool:
        return settings.REMOTE_VISION_ENABLED

    async def analyze(
        self,
        image_path: Path,
        *,
        adaptive: bool,
        target: TargetBook | None = None,
    ) -> tuple[list[OCRResultItem], float, float, str, list[int], float]:
        endpoint = settings.REMOTE_VISION_ENDPOINT.strip()
        if not endpoint:
            raise RemoteVisionError("REMOTE_VISION_ENDPOINT is empty.")
        if settings.REMOTE_VISION_PROVIDER.lower() != "modal":
            raise RemoteVisionError(f"Unsupported remote vision provider: {settings.REMOTE_VISION_PROVIDER}")
        if not settings.MODAL_TOKEN_ID or not settings.MODAL_TOKEN_SECRET:
            raise RemoteVisionError("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET are required.")

        started_at = time.perf_counter()
        try:
            encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
            request_payload: dict[str, object] = {
                "image_base64": encoded_image,
                "adaptive": adaptive,
            }
            if target is not None:
                request_payload.update(
                    {
                        "target_title": target.title,
                        "target_author": target.author,
                        "target_call_number": target.call_number,
                    }
                )
            payload = await asyncio.to_thread(
                self._post_json,
                endpoint,
                request_payload,
            )
            response = RemoteVisionResponse.model_validate(payload)
        except ValidationError as exc:
            raise RemoteVisionError(f"Modal returned an invalid response: {exc}") from exc
        except Exception as exc:
            raise RemoteVisionError(f"Modal vision request failed after {time.perf_counter() - started_at:.1f}s: {exc}") from exc

        items = [OCRResultItem.model_validate(item.model_dump()) for item in response.items]
        return (
            items,
            response.detection_seconds,
            response.ocr_seconds,
            response.model_sha256,
            response.precision_retry_orders,
            response.precision_ocr_seconds,
        )

    @staticmethod
    def _post_json(endpoint: str, payload: dict[str, object]) -> object:
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Modal-Key": settings.MODAL_TOKEN_ID,
                "Modal-Secret": settings.MODAL_TOKEN_SECRET,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.REMOTE_VISION_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RemoteVisionError(f"Modal HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RemoteVisionError(f"Modal connection failed: {exc.reason}") from exc


remote_vision_service = RemoteVisionService()
