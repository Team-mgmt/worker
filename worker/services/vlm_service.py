from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from worker.core.config import settings


class VLMSpine(BaseModel):
    order: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    raw_text: str | None = None
    call_number: str | None = None
    title: str | None = None
    author: str | None = None
    confidence: float | None = None


class VLMAnalyzeResult(BaseModel):
    spines: list[VLMSpine] = Field(default_factory=list)


class VLMServiceError(RuntimeError):
    pass


SYSTEM_PROMPT = """You extract Korean library book spines from shelf photos.
Return only valid JSON. Do not include markdown.
If a value is not visible, use null or an empty string.
Never invent book titles or call numbers that are not visible."""

USER_PROMPT = """Analyze this library shelf image.

Return JSON in this exact shape:
{
  "spines": [
    {
      "order": 1,
      "bbox": [x1, y1, x2, y2],
      "raw_text": "all visible text on the spine",
      "call_number": "visible Korean call number, e.g. 813.7 한12ㅈ",
      "title": "visible title",
      "author": "visible author",
      "confidence": 0.0
    }
  ]
}

Rules:
- order must be left-to-right.
- Return one item per physical book spine. Do not merge adjacent books into one bbox.
- bbox must tightly cover only that book spine, using approximate normalized coordinates from 0 to 1000 in the original image.
- Focus on book spines only. Ignore shelf edges, background, hands, labels not attached to a book, and gaps between books.
- Prefer call numbers and visible labels over guessing titles.
- Use Korean text exactly as visible when possible."""


def _image_data_url(image_path: Path) -> str:
    max_edge = settings.VLM_IMAGE_MAX_EDGE
    jpeg_quality = settings.VLM_IMAGE_JPEG_QUALITY

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image.thumbnail((max_edge, max_edge))

        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    mime_type = "image/jpeg"
    return f"data:{mime_type};base64,{encoded}"


def _extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _post_chat_completion(image_path: Path) -> str:
    api_key = settings.VLM_API_KEY or settings.OPENAI_API_KEY
    if not api_key:
        raise VLMServiceError("VLM_API_KEY or OPENAI_API_KEY is required for VLM analysis.")

    base_url = settings.VLM_API_BASE_URL.rstrip("/")
    request_body = {
        "model": settings.VLM_MODEL,
        "temperature": 0,
        "max_tokens": settings.VLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _image_data_url(image_path),
                            "detail": settings.VLM_IMAGE_DETAIL,
                        },
                    },
                ],
            },
        ],
    }

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.VLM_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise VLMServiceError(f"VLM request failed: {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise VLMServiceError(f"VLM request failed: {exc.reason}") from exc

    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VLMServiceError("VLM response did not contain message content.") from exc


async def analyze_shelf_image_with_vlm(image_path: Path) -> VLMAnalyzeResult:
    try:
        raw_content = await asyncio.wait_for(
            asyncio.to_thread(_post_chat_completion, image_path),
            timeout=settings.VLM_REQUEST_TIMEOUT_SECONDS + 5,
        )
    except TimeoutError as exc:
        raise VLMServiceError(
            f"VLM request timed out after {settings.VLM_REQUEST_TIMEOUT_SECONDS} seconds."
        ) from exc

    try:
        return VLMAnalyzeResult.model_validate(_extract_json(raw_content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VLMServiceError(f"VLM response JSON validation failed: {exc}") from exc
