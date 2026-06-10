"""Render TEXT areas onto template images for better alignment matching.

Mirrors shelfalign-web's ``TeacherExamFileService`` text-rendering logic: TEXT areas
are pulled from ``ExamPaperArea`` (font style on ``area.data``, textContent
template on ``area.area_type.data``), placeholders are substituted with
Exam/ExamRound fields, and the result is drawn at the area's pixel bounds.

The rendering does not need to be pixel-perfect against the printed paper —
it just gives the matcher (RoMaV2) more anchor strokes in regions that would
otherwise be blank on the template.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from . import fonts
from .util import uuid_to_base64url

if TYPE_CHECKING:
    import cv2  # noqa: F401
    from types_aiobotocore_s3 import S3Client

    from .generated.models import Exam, ExamPaperArea, ExamRound
    from .loggers import BaseLogger

# CSS font-weight → font file weight suffix (matches shelfalign-web's fontWeightMap).
_FONT_WEIGHT_MAP: dict[str, str] = {
    "normal": "Regular",
    "bold": "Bold",
}

_FALLBACK_FONT_FILE = "Pretendard-Regular"


class _AreaOverride(BaseModel):
    """Per-area override payload mirroring shelfalign-web's inner zod object.

    zod schema (shelfalign-web/packages/schema/src/models/exam.ts):
        z.object({ fontSize: z.number().optional() })

    ``z.number().optional()`` accepts a numeric value or ``undefined`` (a
    missing key) — explicit ``null`` makes ``safeParse`` fail. Strict
    numeric types reject string/number coercion; the model_validator
    rejects explicit-null inputs; the field_validator rejects Python
    ``bool`` (which would otherwise satisfy ``StrictInt`` since
    ``bool`` subclasses ``int``).
    """

    model_config = ConfigDict(extra="ignore")

    fontSize: StrictFloat | StrictInt | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null_font_size(cls, data: object) -> object:
        # ``z.number().optional()`` differs from ``.nullish()``: it allows
        # the key to be absent but rejects an explicit ``null`` value.
        # Pydantic treats both as ``None`` once the field is parsed, so we
        # inspect the raw input dict to tell them apart.
        if isinstance(data, dict) and "fontSize" in data and data["fontSize"] is None:
            raise ValueError("fontSize cannot be null; omit the key for 'no override'")
        return data

    @field_validator("fontSize", mode="before")
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("fontSize must be a number, not bool")
        return value


class _ExamMetadataV1(BaseModel):
    """Top-level exam.metadata payload (shelfalign-web's ``ExamMetadataV1Schema``).

    zod-equivalent validation semantics — zod's ``safeParse`` is
    all-or-nothing, so any malformed template entry rejects the whole
    payload and the backend falls back to ``area.data.fontSize`` for every
    area. Pydantic raises ``ValidationError`` with the same property:
    one bad ``template[id].fontSize`` invalidates the entire metadata,
    which the caller catches and treats as "no overrides".
    """

    model_config = ConfigDict(extra="ignore")

    version: Literal["1"]
    template: dict[str, _AreaOverride]


def _font_size_overrides_from_exam_metadata(metadata: object) -> dict[str, float]:
    """Extract ``{areaId: fontSize}`` overrides from ``exam.metadata``.

    Returns ``{}`` if the metadata doesn't satisfy the v1 schema — same
    behavior the backend exhibits when ``safeParse`` fails. fontSize
    being absent (``z.number().optional()``) is valid; that area simply
    has no override and uses ``area.data.fontSize``.
    """
    try:
        parsed = _ExamMetadataV1.model_validate(metadata)
    except (ValidationError, TypeError):
        return {}
    return {
        area_id: float(override.fontSize)
        for area_id, override in parsed.template.items()
        if override.fontSize is not None
    }


def _substitute_text_variables(
    content: str,
    *,
    exam_name: str,
    exam_title: str,
    exam_year: str,
    exam_round_name: str,
    exam_round_number: str,
    exam_id_b64: str,
) -> str:
    """Substitute placeholder tokens; mirrors shelfalign-web's ``substituteTextVariables``."""
    return (
        content.replace("{EXAM_NAME}", exam_name)
        .replace("{EXAM_TITLE}", exam_title)
        .replace("{EXAM_YEAR}", exam_year)
        .replace("{EXAM_ROUND_NAME}", exam_round_name)
        # `{EXAM_ROUND_NUMBER}` expands to "<n>회"; eat a literal `회` immediately
        # after the token so older templates written as `{EXAM_ROUND_NUMBER}회`
        # still render as `<n>회` rather than `<n>회회`.
        .replace("{EXAM_ROUND_NUMBER}회", exam_round_number)
        .replace("{EXAM_ROUND_NUMBER}", exam_round_number)
        .replace("{EXAM_ID}", exam_id_b64)
    )


def _format_exam_name(exam: Exam) -> str:
    """Mirror shelfalign-web ``formatExamName``: join non-empty year, title, "<n>회"."""
    parts: list[str] = []
    if exam.year:
        parts.append(exam.year)
    if exam.title:
        parts.append(exam.title)
    if exam.round_number is not None:
        parts.append(f"{exam.round_number}회")
    return " ".join(parts)


async def _resolve_font(
    client: S3Client,
    bucket: str,
    font_family: str,
    weight_css: str,
    logger: BaseLogger | None,
) -> ImageFont.FreeTypeFont | None:
    """Resolve a font family+weight to a loaded PIL font, with fallback to Pretendard-Regular."""
    weight = _FONT_WEIGHT_MAP.get(weight_css, "Regular")
    primary = f"{font_family}-{weight}"

    candidates = [primary]
    if primary != _FALLBACK_FONT_FILE:
        candidates.append(_FALLBACK_FONT_FILE)

    for name in candidates:
        data = await fonts.get_font_bytes(client, bucket, name)
        if data is None:
            continue
        # ImageFont.truetype takes the size on load; we override via .font_variant
        # below per area. Use size=10 as a placeholder.
        try:
            return ImageFont.truetype(io.BytesIO(data), size=10)
        except OSError:
            if logger is not None:
                await logger.warn(f"[text_render] Failed to parse font file {name}; trying fallback")
            continue

    if logger is not None:
        await logger.warn(
            f"[text_render] No font available for family={font_family!r} weight={weight_css!r}; skipping text areas using this font"
        )
    return None


async def render_text_areas_on_template(
    *,
    client: S3Client,
    bucket: str,
    template_image: np.ndarray,
    areas: list[ExamPaperArea],
    exam: Exam,
    exam_round: ExamRound,
    recognition_scale: float,
    logger: BaseLogger | None = None,
) -> int:
    """Mutate ``template_image`` in place, drawing each TEXT area's text content.

    Args:
        client: S3 client used to fetch font files on miss.
        bucket: S3 bucket holding ``common/fonts/<name>.ttf``.
        template_image: RGB array (uint8). Mutated in place.
        areas: All ExamPaperArea rows for the paper; non-TEXT entries are
            ignored. ``area.area_type`` must be eagerly loaded.
        exam, exam_round: Provide placeholder values.
        recognition_scale: User-unit → recognition-pixel multiplier. Same scale
            used by the QR render and bubble crop bounds.
        logger: Optional logger for warnings.

    Returns:
        The number of TEXT areas actually drawn (useful for tests/profiling).
    """
    text_areas = [a for a in areas if a.area_type is not None and a.area_type.base_type == "TEXT"]
    if not text_areas:
        return 0

    # Per-area fontSize overrides live on ``exam.metadata.template[areaId]``.
    # The backend's PDF renderer reads these before falling back to
    # ``area.data.fontSize``; the worker must do the same so the rendered
    # template's glyph sizes match the printed paper exactly.
    font_size_overrides = _font_size_overrides_from_exam_metadata(getattr(exam, "metadata_", None))

    exam_round_number = "" if exam.round_number is None else f"{exam.round_number}회"
    exam_id_b64 = uuid_to_base64url(exam.id)
    text_vars = {
        "exam_name": _format_exam_name(exam),
        "exam_title": exam.title,
        "exam_year": exam.year,
        "exam_round_name": exam_round.name,
        "exam_round_number": exam_round_number,
        "exam_id_b64": exam_id_b64,
    }

    pil_image = Image.fromarray(template_image)
    draw = ImageDraw.Draw(pil_image)

    rendered_count = 0
    # Cache resolved fonts within this call so multiple areas sharing a
    # family+weight don't repeat the S3 lookup / PIL parse.
    font_cache: dict[tuple[str, str], ImageFont.FreeTypeFont | None] = {}

    for area in text_areas:
        pos_x = int(round(area.pos_x * recognition_scale))
        pos_y = int(round(area.pos_y * recognition_scale))
        width = max(1, int(round(area.width * recognition_scale)))
        height = max(1, int(round(area.height * recognition_scale)))

        # Clear the area to white so matcher anchors don't pick up template
        # ink that happens to sit underneath a defined TEXT area (e.g. SVG
        # placeholder glyphs from the layout export). ImageDraw.rectangle
        # treats both corner coordinates as inclusive, so subtract 1 from the
        # bottom-right corner to keep the wipe strictly within declared bounds.
        draw.rectangle(
            (pos_x, pos_y, pos_x + width - 1, pos_y + height - 1),
            fill=(255, 255, 255),
        )

        area_type_data = area.area_type.data if isinstance(area.area_type.data, dict) else {}
        text_content = area_type_data.get("textContent")
        if not text_content:
            continue

        text = _substitute_text_variables(str(text_content), **text_vars)
        if not text:
            continue

        area_data = area.data if isinstance(area.data, dict) else {}
        font_family = str(area_data.get("fontFamily", "Pretendard"))
        weight_css = str(area_data.get("fontWeight", "normal"))
        override = font_size_overrides.get(str(area.id))
        if override is not None:
            font_size = override
        else:
            try:
                font_size = float(area_data.get("fontSize", 16))
            except (TypeError, ValueError):
                font_size = 16.0
        text_align = str(area_data.get("textAlign", "left"))

        font_key = (font_family, weight_css)
        base_font = font_cache.get(font_key)
        if font_key not in font_cache:
            base_font = await _resolve_font(client, bucket, font_family, weight_css, logger)
            font_cache[font_key] = base_font
        if base_font is None:
            continue

        font_size_px = max(1, int(round(font_size * recognition_scale)))
        try:
            font = base_font.font_variant(size=font_size_px)
        except (OSError, ValueError):
            continue

        # Vertically center inside the area (mirrors shelfalign-web's PDFKit path).
        try:
            ascent, descent = font.getmetrics()
            text_h = ascent + descent
        except AttributeError:
            text_h = font_size_px
        vertical_offset = max(0, (height - text_h) // 2)

        if text_align in ("right", "center"):
            try:
                tbbox = draw.textbbox((0, 0), text, font=font, anchor="la")
                text_w = int(round(tbbox[2] - tbbox[0]))
            except (TypeError, ValueError):
                text_w = 0
            if text_align == "right":
                text_x = pos_x + width - text_w
            else:
                text_x = pos_x + (width - text_w) // 2
        else:
            text_x = pos_x

        draw.text((text_x, pos_y + vertical_offset), text, fill=(0, 0, 0), font=font, anchor="la")
        rendered_count += 1

    # PIL renders into its own buffer; copy back into the caller's array so the
    # mutation (white-fill rectangles + any drawn text) is visible to in-flight
    # references (e.g. the binarization task). We always copy back when there
    # are TEXT areas because each one clears its bounding box to white.
    rendered = np.asarray(pil_image)
    template_image[:, :, :] = rendered
    return rendered_count
