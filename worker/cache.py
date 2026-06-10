"""Disk-backed caches for expensive processor outputs.

Entries are stored as files under CACHE_DIR. The OS page cache handles
hot-entry memory residency and evicts under memory pressure, so there is
no explicit in-memory bound.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import cv2
import numpy as np

from .paths import CACHE_DIR
from .types import ImageProcessingParams

if TYPE_CHECKING:
    from .generated.models import ExamPaperArea


def _ts(value: datetime.datetime) -> str:
    """Stable ISO-8601 stamp for cache keys (UTC, microsecond precision)."""
    return value.isoformat()

TEMPLATE_THRESH_SUBDIR = "template_thresh"
TEMPLATE_BASELINE_FILL_MAP_SUBDIR = "template_baseline_fill_map"
SVG_PNG_SUBDIR = "svg_png"


def _template_thresh_cache_key_params(params: ImageProcessingParams) -> dict[str, int | float | bool]:
    """Return only params that affect template threshold generation."""
    return {
        "recognition_scale": params.recognition_scale,
        "denoise_ksize": params.denoise_ksize,
        "adaptive_block_ratio": params.adaptive_block_ratio,
        "adaptive_block_min": params.adaptive_block_min,
        "adaptive_c": params.adaptive_c,
        "post_thresh_ksize": params.post_thresh_ksize,
        "morph_open_ksize": params.morph_open_ksize,
        "morph_close_ksize": params.morph_close_ksize,
        "adaptive_kernel_scaling": params.adaptive_kernel_scaling,
        "morph_close_first": params.morph_close_first,
        "min_morph_kernel_size": params.min_morph_kernel_size,
        "reference_template_width": params.reference_template_width,
        # SVG render width changes the rasterized template input even when
        # recognition_scale is identical (e.g., when recognition_max_width
        # bottlenecks the downscale), so it must invalidate the cached threshold.
        "svg_min_render_width": params.svg_min_render_width,
    }


def _template_baseline_fill_map_key_params(params: ImageProcessingParams) -> dict[str, int | float | bool | str]:
    """Return only params that affect template baseline measurements."""
    return {
        **_template_thresh_cache_key_params(params),
        "bubble_padding_ratio": params.bubble_padding_ratio,
        "bubble_measurement_shape": params.bubble_measurement_shape,
        "bubble_roi_use_morphology": params.bubble_roi_use_morphology,
        "bubble_roi_morph_close_first": params.bubble_roi_morph_close_first,
        "bubble_roi_morph_open_ksize": params.bubble_roi_morph_open_ksize,
        "bubble_roi_morph_close_ksize": params.bubble_roi_morph_close_ksize,
    }


def _template_thresh_path(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
) -> Path:
    # ExamPaper.updatedAt covers area/layout edits; Exam.updatedAt covers
    # changes to title/year/round_number; ExamRound.updatedAt covers per-round
    # fields (notably name) that render into TEXT areas via `{EXAM_ROUND_NAME}`.
    # Including all three keeps the cache from serving template pixels rendered
    # against a different round's text.
    key = (
        f"template_thresh_v3|{exam_paper_id}|{_ts(exam_paper_updated_at)}|"
        f"{exam_id}|{_ts(exam_updated_at)}|"
        f"{exam_round_id}|{_ts(exam_round_updated_at)}|"
        f"{background_image}|{json.dumps(_template_thresh_cache_key_params(params), sort_keys=True)}"
    )
    digest = hashlib.sha256(key.encode()).hexdigest()
    return Path(CACHE_DIR) / TEMPLATE_THRESH_SUBDIR / f"{digest}.png"


def _areas_layout_digest(areas: list[ExamPaperArea]) -> str:
    """Stable signature of area layout, so coordinate edits invalidate baselines.

    Baselines are measured against per-bubble coordinates derived from area
    pos/size and the children dict. If a layout is edited under the same
    background_image, the cached map would otherwise apply to moved bubbles.
    """
    layout = [
        {
            "id": str(area.id),
            "pos_x": float(area.pos_x),
            "pos_y": float(area.pos_y),
            "width": float(area.width),
            "height": float(area.height),
            "children": area.data.get("children", {}) if isinstance(area.data, dict) else {},
        }
        for area in sorted(areas, key=lambda a: str(a.id))
    ]
    payload = json.dumps(layout, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _template_baseline_fill_map_path(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
    areas: list[ExamPaperArea],
) -> Path:
    # v4 adds ExamRound identity/updatedAt so two rounds under the same exam
    # can't share a cached baseline whose template was rendered with the
    # other round's `{EXAM_ROUND_NAME}` text.
    key = (
        f"baseline_fill_map_v4|{exam_paper_id}|{_ts(exam_paper_updated_at)}|"
        f"{exam_id}|{_ts(exam_updated_at)}|"
        f"{exam_round_id}|{_ts(exam_round_updated_at)}|"
        f"{background_image}|{_areas_layout_digest(areas)}|"
        f"{json.dumps(_template_baseline_fill_map_key_params(params), sort_keys=True)}"
    )
    digest = hashlib.sha256(key.encode()).hexdigest()
    return Path(CACHE_DIR) / TEMPLATE_BASELINE_FILL_MAP_SUBDIR / f"{digest}.json"


def svg_png_path(digest: str) -> Path:
    """Local content-addressable path for a PNG rasterized from SVG bytes with the given SHA-256 digest."""
    return Path(CACHE_DIR) / SVG_PNG_SUBDIR / f"{digest}.png"


def get_template_thresh(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
) -> np.ndarray | None:
    """Return the cached binarized template, or None on miss."""
    path = _template_thresh_path(
        exam_paper_id,
        exam_paper_updated_at,
        exam_id,
        exam_updated_at,
        exam_round_id,
        exam_round_updated_at,
        background_image,
        params,
    )
    if not path.exists():
        return None
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    return image


def put_template_thresh(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
    image: np.ndarray,
) -> None:
    """Write the binarized template atomically (tmp file + rename)."""
    path = _template_thresh_path(
        exam_paper_id,
        exam_paper_updated_at,
        exam_id,
        exam_updated_at,
        exam_round_id,
        exam_round_updated_at,
        background_image,
        params,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the .png extension on the tmp file so cv2.imwrite picks the PNG encoder.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp.png")
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError("Failed to encode template threshold image as PNG")
    encoded.tofile(tmp)
    os.replace(tmp, path)


def get_template_baseline_fill_map(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
    areas: list[ExamPaperArea],
) -> dict[str, float] | None:
    """Return the cached per-bubble template baseline fill map, or None on miss."""
    path = _template_baseline_fill_map_path(
        exam_paper_id,
        exam_paper_updated_at,
        exam_id,
        exam_updated_at,
        exam_round_id,
        exam_round_updated_at,
        background_image,
        params,
        areas,
    )
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    return {str(key): float(value) for key, value in data.items()}


def put_template_baseline_fill_map(
    exam_paper_id: UUID,
    exam_paper_updated_at: datetime.datetime,
    exam_id: UUID,
    exam_updated_at: datetime.datetime,
    exam_round_id: UUID,
    exam_round_updated_at: datetime.datetime,
    background_image: str,
    params: ImageProcessingParams,
    areas: list[ExamPaperArea],
    fill_map: dict[str, float],
) -> None:
    """Write the template baseline fill map atomically (tmp file + rename)."""
    path = _template_baseline_fill_map_path(
        exam_paper_id,
        exam_paper_updated_at,
        exam_id,
        exam_updated_at,
        exam_round_id,
        exam_round_updated_at,
        background_image,
        params,
        areas,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    serializable = {key: float(value) for key, value in fill_map.items()}
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(serializable, fp, sort_keys=True)
    os.replace(tmp, path)
