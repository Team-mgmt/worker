from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import pathlib
import re
import uuid
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Callable, Literal, Optional, TypeVar

import aiofiles
import botocore.exceptions
import cairosvg
import cv2
import numpy as np
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from zxingcpp import Barcode, Point

if TYPE_CHECKING:
    from pathlib import Path

    from types_aiobotocore_s3 import S3Client

from .cache import svg_png_path
from .models import SoftDeleteMixin
from .paths import IMAGES_DIR, TEMPLATES_DIR
from .types import PositionLiteral, ProcessError

# Bumped whenever the rasterization recipe (background / format / sizing
# strategy) changes, so cached PNGs from prior recipes are not served. The
# per-call ``svg_min_render_width`` is also folded into the cache digest, so
# different min-width values produce different cache entries automatically;
# this version is bumped only for *recipe* changes that don't show up in the
# min-width parameter.
SVG_RENDER_VERSION = "v4"

# S3 key prefix for the content-addressable PNG cache derived from SVG sources.
# Lives in the same bucket as templates; override via env var if a different
# location is desired.
SVG_PNG_CACHE_S3_PREFIX = os.getenv("SVG_PNG_CACHE_S3_PREFIX", "cache/templates/svg-png/")

# S3 error codes that indicate a cache miss (treat as "not cached", not as failure).
_S3_NOT_FOUND_CODES = {"NoSuchKey", "NoSuchBucket", "404"}

# Upper bound on rendered SVG pixel area. cairosvg allocates the full pixel
# buffer (4 bytes/px RGBA) before we ever see the result, so a malformed or
# upscaled SVG with huge dimensions could OOM the worker. ~16 MP comfortably
# fits A3 at 300 DPI (~17 MP) and tabloid at 300 DPI (~17 MP) — legitimate
# templates stay well under this whether rendered at intrinsic dims or upscaled.
SVG_MAX_INTRINSIC_PIXELS = 16_000_000

# CSS unit → pixels at 96 DPI. Mirrors cairosvg's default DPI so the pre-render
# guard estimates the same pixel dimensions cairosvg will produce.
_SVG_LENGTH_UNITS_TO_PX = {
    "px": 1.0,
    "pt": 96.0 / 72.0,
    "mm": 96.0 / 25.4,
    "cm": 96.0 / 2.54,
    "in": 96.0,
    "pc": 96.0 / 6.0,
}
# Accept the full CSS/SVG numeric grammar: optional sign; mantissa is either
# `<digits>.<digits>?` or `.<digits>` (so `1`, `1.5`, `1.`, and `.5` all match);
# optional `e±<digits>` exponent. Without this, valid attributes like `.5in`
# or `+10mm` would fall through to the SVG_DIMENSIONS_INDETERMINATE path.
_SVG_LENGTH_RE = re.compile(
    r"^\s*([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*(px|pt|mm|cm|in|pc)?\s*$"
)


async def prepare_image(
    client: S3Client,
    bucket_name: str,
    image_id: uuid.UUID,
    image_key: str,
    image_type: Literal["images", "templates"],
    on_access: Optional[Callable[[str], None]] = None,
    *,
    svg_min_render_width: int | None = None,
) -> tuple[cv2.typing.MatLike, float]:
    """
    Download an image from S3 if not cached locally, then read and return it.

    Args:
        client: S3 client
        bucket_name: S3 bucket name
        image_id: UUID to use as local filename
        image_key: S3 object key
        image_type: Type of image ("images" or "templates")
        on_access: Optional callback called with filepath when image is accessed (for LRU tracking)
        svg_min_render_width: Minimum width (px) for SVG rasterization. Required
            when ``image_key`` resolves to an SVG; ignored otherwise. Comes from
            ``ImageProcessingParams.svg_min_render_width``. Smaller intrinsic
            widths are upscaled (preserving aspect ratio, capped by
            ``SVG_MAX_INTRINSIC_PIXELS``) so OMR detection bubbles get enough
            pixels to be noise-robust.

    Returns:
        Tuple of ``(image, source_to_pixel_scale)`` where ``image`` is the
        loaded array (RGB) and ``source_to_pixel_scale`` is the multiplier
        that converts the source's intrinsic coordinate space to raster
        pixels. Always ``1.0`` for raster sources (PNG/JPG); for SVGs it is
        the ratio between the rasterized PNG width and the SVG's intrinsic
        width (≥ 1.0). Callers must propagate this into any pixel-coordinate
        conversion derived from area/template coordinates stored in the
        source's intrinsic units.
    """
    src_extension = pathlib.Path(image_key).suffix
    if src_extension.lower() == ".svg":
        if svg_min_render_width is None:
            # Defensive: the only known SVG callers (template loaders) always
            # pass this in from processing params. Hitting this means a new
            # caller forgot to wire it; surface as a config error rather than
            # silently picking a default that may not match the request's
            # processing params.
            raise ProcessError(
                "svg_min_render_width is required for SVG sources",
                code="SVG_RENDER_CONFIG_MISSING",
                params={"image_key": image_key},
            )
        filepath, source_scale = await _materialize_svg_as_png(
            client, bucket_name, image_key, svg_min_render_width
        )
    else:
        base_dir = IMAGES_DIR if image_type == "images" else TEMPLATES_DIR
        filepath = os.path.join(base_dir, f"{image_id}{src_extension}")
        if not os.path.exists(filepath):
            response = await client.get_object(Bucket=bucket_name, Key=image_key)
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(await response["Body"].read())
        source_scale = 1.0

    if on_access is not None:
        on_access(filepath)

    image = cv2.imread(filepath)
    if image is None:
        raise ProcessError(
            f"Failed to read image from {filepath}",
            code="IMAGE_READ_FAILED",
            params={"filepath": filepath, "source_key": image_key},
        )
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image, source_scale


async def _materialize_svg_as_png(
    client: S3Client, bucket_name: str, svg_key: str, svg_min_render_width: int
) -> tuple[str, float]:
    """Resolve an SVG source to a local PNG path, using a content-addressable cache.

    The SVG is fetched from S3 on every call (it may have changed without a key
    change). The resulting PNG is cached:
      1. locally under CACHE_DIR/svg_png/{sha256}.png (L1, on-host),
      2. remotely under SVG_PNG_CACHE_S3_PREFIX{sha256}.png (L2, shared).

    On cache miss at both layers, the SVG is rasterized and pushed to both.
    Returns ``(local_png_path, scale)`` where ``scale`` is the user-unit→pixel
    factor used during rasterization (see ``_resolve_svg_render_dims``). The
    scale is recomputed from the SVG bytes on every call (cheap parse), so it
    is consistent across cache hits and misses without storing it alongside
    the PNG.
    """
    response = await client.get_object(Bucket=bucket_name, Key=svg_key)
    svg_bytes = await response["Body"].read()
    # Salt the digest with the render version AND ``svg_min_render_width``:
    # different min-widths produce different rasters from the same SVG bytes,
    # so they must occupy distinct cache entries. Bumping the version still
    # forces a global invalidation when other recipe details change.
    digest = hashlib.sha256(
        SVG_RENDER_VERSION.encode()
        + b"|"
        + str(svg_min_render_width).encode()
        + b"|"
        + svg_bytes
    ).hexdigest()

    # Resolve render dims up front: this validates intrinsic dims (cap +
    # parseability) and computes the upscale factor. Doing it before checking
    # the local cache means a malformed/oversized SVG fails fast with the
    # same error whether or not a stale PNG happens to sit in the cache —
    # otherwise a bad SVG could "pass" via stale cached PNG and only fail
    # later when re-rasterized.
    output_w, output_h, scale = _resolve_svg_render_dims(svg_bytes, svg_min_render_width)

    local_path = svg_png_path(digest)
    if local_path.exists():
        return str(local_path), scale

    png_bytes = await _fetch_or_render_svg_png(
        client, bucket_name, svg_bytes, digest, output_w, output_h
    )
    await _atomic_write_bytes(local_path, png_bytes)
    return str(local_path), scale


async def _fetch_or_render_svg_png(
    client: S3Client,
    bucket_name: str,
    svg_bytes: bytes,
    digest: str,
    output_width: int,
    output_height: int,
) -> bytes:
    """Return PNG bytes for the SVG: pull from S3 cache if present, otherwise rasterize and upload."""
    s3_key = f"{SVG_PNG_CACHE_S3_PREFIX}{digest}.png"
    try:
        cached = await client.get_object(Bucket=bucket_name, Key=s3_key)
        return await cached["Body"].read()
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code not in _S3_NOT_FOUND_CODES:
            raise

    # Render at the resolved output dimensions, which preserves the SVG's
    # aspect ratio (cairosvg derives height from output_width when only the
    # width is given). For SVGs with intrinsic width >= SVG_MIN_RENDER_WIDTH
    # this is the intrinsic size; smaller SVGs are upscaled so OMR bubbles
    # have enough pixels to be noise-robust. The user-unit→raster-pixel scale
    # is propagated back via ``_materialize_svg_as_png`` so area coordinates
    # (in SVG user units) still translate correctly through the recognition
    # resize. White background so the raster (after BGR alpha-strip in
    # cv2.imread) matches the white-paper assumption of the OMR pipeline.
    # cairosvg.svg2png is CPU-bound; offload so we don't stall the event loop.
    png_bytes = await asyncio.to_thread(
        cairosvg.svg2png,
        bytestring=svg_bytes,
        background_color="white",
        output_width=output_width,
        output_height=output_height,
    )
    await client.put_object(Bucket=bucket_name, Key=s3_key, Body=png_bytes, ContentType="image/png")
    return png_bytes


def _parse_svg_length(value: str | None) -> float | None:
    """Return ``value`` converted to pixels at 96 DPI, or ``None`` if unparseable.

    Unitless lengths are treated as pixels (matching SVG's user-unit convention).
    Percentages and other relative units return ``None`` since they can't be
    resolved without rendering context. Non-finite results (e.g. ``1e309``
    parsing to ``inf``) are also returned as ``None`` so the caller routes them
    through the standard validation error path instead of an ``OverflowError``
    later in pixel-area math.
    """
    if not value:
        return None
    match = _SVG_LENGTH_RE.match(value)
    if not match:
        return None
    magnitude = float(match.group(1))
    unit = match.group(2) or "px"
    pixels = magnitude * _SVG_LENGTH_UNITS_TO_PX[unit]
    if not math.isfinite(pixels):
        return None
    return pixels


# SVG viewBox separators per the spec are whitespace and/or commas.
_VIEWBOX_SEP_RE = re.compile(r"[\s,]+")


def _resolve_svg_render_dims(
    svg_bytes: bytes, min_render_width: int
) -> tuple[int, int, float]:
    """Return ``(output_width, output_height, scale)`` for SVG rasterization.

    Parses the root element to read ``width``/``height`` (with unit conversion
    at 96 DPI to mirror cairosvg) and falls back to ``viewBox`` dimensions
    when either attribute is missing. SVGs without discoverable dimensions or
    with intrinsic pixel area over ``SVG_MAX_INTRINSIC_PIXELS`` are rejected.

    Small SVGs are upscaled so their rasterization is at least
    ``min_render_width`` wide (preserving aspect ratio), with the upscale
    factor clamped down if the pixel cap would otherwise be exceeded. The
    returned ``scale`` is ``output_width / intrinsic_width`` — the multiplier
    that converts SVG user units to raster pixels. Callers propagate this
    factor into the recognition scale so area coordinates (still in user-unit
    space) translate to the correct recognition pixel positions.
    """
    try:
        root = ET.fromstring(svg_bytes)
    except ET.ParseError as exc:
        raise ProcessError(
            f"Failed to parse SVG: {exc}",
            code="SVG_PARSE_FAILED",
            params={"reason": str(exc)},
        ) from exc

    width = _parse_svg_length(root.attrib.get("width"))
    height = _parse_svg_length(root.attrib.get("height"))

    if width is None or height is None:
        viewbox = root.attrib.get("viewBox")
        if viewbox:
            # SVG spec allows comma and/or whitespace separators between
            # viewBox values (e.g. "0 0 640 480" or "0,0,640,480"), so split
            # on either rather than only whitespace.
            parts = [p for p in _VIEWBOX_SEP_RE.split(viewbox.strip()) if p]
            if len(parts) == 4:
                try:
                    vb_w = float(parts[2])
                    vb_h = float(parts[3])
                except ValueError:
                    pass
                else:
                    if math.isfinite(vb_w) and math.isfinite(vb_h) and vb_w > 0 and vb_h > 0:
                        # When only one of width/height is present, derive the
                        # missing side from the given side and the viewBox
                        # aspect ratio rather than copying viewBox dimensions
                        # directly. cairosvg honors aspect ratio: an SVG with
                        # `height="100" viewBox="0 0 100000 1"` actually
                        # renders at 10_000_000 × 100, not 100_000 × 100, so
                        # naively copying vb_w would under-estimate the pixel
                        # area and let pathological inputs slip past the cap.
                        if width is None and height is not None:
                            width = height * (vb_w / vb_h)
                        elif height is None and width is not None:
                            height = width * (vb_h / vb_w)
                        else:  # both missing — viewBox dictates both
                            width, height = vb_w, vb_h

    if width is None or height is None or width <= 0 or height <= 0:
        raise ProcessError(
            "SVG has no usable intrinsic dimensions (need width+height or viewBox)",
            code="SVG_DIMENSIONS_INDETERMINATE",
            params={"width": str(root.attrib.get("width")), "height": str(root.attrib.get("height"))},
        )

    # ``width``/``height`` are guaranteed finite here: ``_parse_svg_length``
    # filters non-finite results, and the viewBox branch only assigns when
    # ``math.isfinite`` holds. Skip the OverflowError-prone ``int(...)`` until
    # we know the product is bounded.
    intrinsic_pixels = width * height
    if intrinsic_pixels > SVG_MAX_INTRINSIC_PIXELS:
        raise ProcessError(
            f"SVG intrinsic pixel area {intrinsic_pixels:.0f} exceeds limit {SVG_MAX_INTRINSIC_PIXELS}",
            code="SVG_TOO_LARGE",
            params={
                "width": int(width),
                "height": int(height),
                "pixels": int(intrinsic_pixels),
                "limit": SVG_MAX_INTRINSIC_PIXELS,
            },
        )

    # Upscale to ``min_render_width`` when the SVG is smaller than that, so
    # OMR bubbles end up with enough pixels to be noise-robust. The cap on
    # final pixels still applies — for unusually tall+narrow SVGs where the
    # full upscale would blow past the cap, we clamp the factor down to fit
    # rather than reject (intrinsic was already accepted).
    if width >= min_render_width:
        scale = 1.0
    else:
        target_scale = min_render_width / width
        cap_scale = math.sqrt(SVG_MAX_INTRINSIC_PIXELS / intrinsic_pixels)
        scale = min(target_scale, cap_scale)
        # ``cap_scale`` is > 1 here (intrinsic_pixels passed the cap above)
        # but defensively floor at 1.0 — never *downscale* an SVG.
        scale = max(1.0, scale)

    # Truncate (don't round) so the cap-clamped case can't slip 1 px over the
    # cap from rounding-up: ``output_w * output_h <= width*height*scale^2``
    # is guaranteed by floor, but not by round-half-to-even.
    output_width = max(1, int(width * scale))
    output_height = max(1, int(height * scale))
    return output_width, output_height, scale


async def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (tmp file + rename) so partial files are never observed.

    The tmp suffix is per-call unique (uuid4) so concurrent writes to the same
    final path never collide on the tmp file: without this, two coroutines
    materializing the same SVG digest could clobber each other's writes (one
    coroutine's ``open("wb")`` truncating while another is still writing) or
    have a write leak into the renamed target inode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    async with aiofiles.open(tmp, "wb") as f:
        await f.write(data)
    os.replace(tmp, path)


def point_to_tuple(pos: Point) -> tuple[float, float]:
    return (float(pos.x), float(pos.y))


def get_barcode_corners(result: Barcode, point: PositionLiteral):
    if point == "LT":
        return point_to_tuple(result.position.top_left)
    if point == "RT":
        return point_to_tuple(result.position.top_right)
    if point == "RB":
        return point_to_tuple(result.position.bottom_right)
    if point == "LB":
        return point_to_tuple(result.position.bottom_left)


def _barcode_to_image_array(barcode: Barcode, size_hint: int) -> cv2.typing.MatLike:
    try:
        qr_image = barcode.to_image(scale=1, add_hrt=False, add_quiet_zones=False)
    except TypeError:
        qr_image = barcode.to_image(size_hint=size_hint, with_hrt=False, with_quiet_zones=False)
    return np.array(qr_image, dtype=np.uint8)


ModelT = TypeVar("ModelT", bound=SoftDeleteMixin)
IdT = TypeVar("IdT")


async def get_by_id(session: AsyncSession, model: type[ModelT], id: IdT) -> ModelT | None:
    stmt: Select[tuple[ModelT]] = select(model).where(
        model.id == id,
        model.deleted_at.is_(None),
    )

    result = await session.scalars(stmt)
    return result.one_or_none()


def base64url_to_uuid(b64url_str: str) -> uuid.UUID:
    padding = "=" * (-len(b64url_str) % 4)
    b64_str = b64url_str.replace("-", "+").replace("_", "/") + padding
    byte_data = base64.b64decode(b64_str)
    return uuid.UUID(bytes=byte_data)


def uuid_to_base64url(value: uuid.UUID) -> str:
    """Encode a UUID as an unpadded base64url string (matches shelfalign-web)."""
    # shelfalign-web's uuidToBase64Url strips dashes, hex-decodes, then base64url
    # encodes — that produces a 22-char unpadded result. Mirror it here so
    # the same encoding lands in scan QR codes and rendered template text.
    return base64.urlsafe_b64encode(value.bytes).rstrip(b"=").decode("ascii")


def render_qrcode_on_template(
    template_image: cv2.typing.MatLike,
    barcode: Barcode,
    pos_x: int,
    pos_y: int,
    width: int,
    height: int,
    inplace: bool = False,
) -> cv2.typing.MatLike:
    """Render a QR code on the template image at the specified position.

    Uses the detected barcode's to_image() method to ensure the exact same
    QR code pattern (version, mask, error correction) is rendered.

    Args:
        template_image: Template image (RGB format)
        barcode: The detected Barcode object from the scan
        pos_x: X position in pixels
        pos_y: Y position in pixels
        width: Width of the QR code area in pixels
        height: Height of the QR code area in pixels
        inplace: If True, mutate ``template_image`` directly. Callers using this
            must guarantee no other thread is reading the array concurrently.

    Returns:
        Template image with QR code rendered (RGB format)
    """
    size_hint = max(width, height)
    qr_array = _barcode_to_image_array(barcode, size_hint)

    if qr_array.shape[0] != height or qr_array.shape[1] != width:
        qr_array = cv2.resize(qr_array, (width, height), interpolation=cv2.INTER_NEAREST)

    qr_rgb = cv2.cvtColor(qr_array, cv2.COLOR_GRAY2RGB)

    result = template_image if inplace else template_image.copy()

    template_h, template_w = result.shape[:2]
    end_x = min(pos_x + width, template_w)
    end_y = min(pos_y + height, template_h)
    actual_width = end_x - pos_x
    actual_height = end_y - pos_y

    if actual_width > 0 and actual_height > 0:
        result[pos_y:end_y, pos_x:end_x] = qr_rgb[:actual_height, :actual_width]

    return result


def is_valid_student_id(student_id: str) -> bool:
    """Check if student_id is valid (no blanks or multiple selections).

    Valid student_id contains only digits 0-9 and does not start with '0' or '1'.
    Invalid if contains '_' (blank) or '*' (multiple selection), or starts with '0' or '1'.
    """
    if not student_id:
        return False
    if student_id[0] == "0" or student_id[0] == "1":
        return False
    for char in student_id:
        if char == "_" or char == "*":
            return False
    return True
