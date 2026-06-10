from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, Field

from .types import AreaMetrics, ImageProcessingParams


class BubbleSpec(BaseModel):
    choice: str
    cx: float
    cy: float
    width: float
    height: float


class IdentifierGroup(BaseModel):
    digit_index: int
    label: str
    bubbles: list[BubbleSpec] = Field(default_factory=list)


class ProblemGroup(BaseModel):
    question_label: str
    bubbles: list[BubbleSpec] = Field(default_factory=list)


class SvgOmrLayout(BaseModel):
    svg_width: float | None = None
    svg_height: float | None = None
    identifier_groups: list[IdentifierGroup] = Field(default_factory=list)
    problem_groups: list[ProblemGroup] = Field(default_factory=list)


class BubbleDetection(BaseModel):
    group_type: str
    group_label: str
    choice: str
    is_filled: bool
    fill_ratio: float
    x: int
    y: int
    width: int
    height: int


class OMRDetectionResult(BaseModel):
    identifier_results: dict[int, list[str]]
    problem_results: dict[str, list[str]]
    metrics: list[BubbleDetection]


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", value)
    if match is None:
        return None
    return float(match.group(1))


def _parse_viewbox(value: str | None) -> tuple[float, float] | tuple[None, None]:
    if value is None:
        return None, None
    parts = value.replace(",", " ").split()
    if len(parts) != 4:
        return None, None
    numbers = [_parse_number(part) for part in parts]
    if any(number is None for number in numbers):
        return None, None
    return float(numbers[2]), float(numbers[3])


def _element_path(element: ET.Element, parent_map: dict[ET.Element, ET.Element]) -> str:
    parts: list[str] = []
    current: ET.Element | None = element
    while current is not None and len(parts) < 5:
        tag = _strip_namespace(current.tag)
        part = tag
        element_id = current.attrib.get("id")
        if element_id:
            part = f"{tag}#{element_id}"
        parts.append(part)
        current = parent_map.get(current)
    return "/".join(reversed(parts))


def summarize_svg_for_llm(svg_text: str, *, max_candidate_shapes: int = 1200, max_text_nodes: int = 300) -> str:
    """Build a compact JSON summary of SVG geometry for the LLM."""
    root = ET.fromstring(svg_text)
    parent_map = {child: parent for parent in root.iter() for child in parent}

    width = _parse_number(root.attrib.get("width"))
    height = _parse_number(root.attrib.get("height"))
    viewbox_width, viewbox_height = _parse_viewbox(root.attrib.get("viewBox"))
    svg_width = viewbox_width or width
    svg_height = viewbox_height or height
    min_dim = min(value for value in [svg_width, svg_height] if value is not None) if svg_width or svg_height else None

    counts: Counter[str] = Counter()
    text_nodes: list[dict[str, Any]] = []
    candidate_shapes: list[dict[str, Any]] = []

    for element in root.iter():
        tag = _strip_namespace(element.tag)
        counts[tag] += 1

        if tag == "text":
            text = " ".join(part.strip() for part in element.itertext() if part.strip())
            if not text:
                continue
            text_nodes.append(
                {
                    "text": text,
                    "x": _parse_number(element.attrib.get("x")),
                    "y": _parse_number(element.attrib.get("y")),
                    "id": element.attrib.get("id"),
                    "class": element.attrib.get("class"),
                    "path": _element_path(element, parent_map),
                }
            )
            continue

        shape: dict[str, Any] | None = None
        if tag == "circle":
            r = _parse_number(element.attrib.get("r"))
            cx = _parse_number(element.attrib.get("cx"))
            cy = _parse_number(element.attrib.get("cy"))
            if r is not None and cx is not None and cy is not None:
                shape = {"tag": tag, "cx": cx, "cy": cy, "width": r * 2.0, "height": r * 2.0}
        elif tag == "ellipse":
            rx = _parse_number(element.attrib.get("rx"))
            ry = _parse_number(element.attrib.get("ry"))
            cx = _parse_number(element.attrib.get("cx"))
            cy = _parse_number(element.attrib.get("cy"))
            if None not in (rx, ry, cx, cy):
                shape = {"tag": tag, "cx": cx, "cy": cy, "width": float(rx) * 2.0, "height": float(ry) * 2.0}
        elif tag == "rect":
            x = _parse_number(element.attrib.get("x"))
            y = _parse_number(element.attrib.get("y"))
            shape_width = _parse_number(element.attrib.get("width"))
            shape_height = _parse_number(element.attrib.get("height"))
            if None not in (x, y, shape_width, shape_height):
                shape = {
                    "tag": tag,
                    "cx": float(x) + float(shape_width) / 2.0,
                    "cy": float(y) + float(shape_height) / 2.0,
                    "width": float(shape_width),
                    "height": float(shape_height),
                }

        if shape is None:
            continue

        if min_dim is not None:
            max_shape_size = min_dim * 0.08
            min_shape_size = min_dim * 0.002
            if not (min_shape_size <= shape["width"] <= max_shape_size and min_shape_size <= shape["height"] <= max_shape_size):
                continue

        shape["id"] = element.attrib.get("id")
        shape["class"] = element.attrib.get("class")
        shape["path"] = _element_path(element, parent_map)
        candidate_shapes.append(shape)

    summary = {
        "svg": {
            "width": svg_width,
            "height": svg_height,
            "viewBox": root.attrib.get("viewBox"),
        },
        "element_counts": dict(counts),
        "candidate_shapes": candidate_shapes[:max_candidate_shapes],
        "candidate_shape_count_total": len(candidate_shapes),
        "text_nodes": text_nodes[:max_text_nodes],
        "text_node_count_total": len(text_nodes),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def build_svg_omr_prompt(svg_summary_json: str) -> str:
    """Prompt Claude to return OMR bubble coordinates in SVG units."""
    return (
        "You are analyzing an exam paper SVG summary.\n"
        "Return only valid JSON.\n"
        "Use the SVG coordinate system from the summary.\n"
        "Include OMR bubble groups for:\n"
        "1. student identifier / exam number marking columns\n"
        "2. problem answer marking rows, especially inquiry-section answers\n"
        "Ignore titles, instructions, logos, decorative boxes, barcodes, and free-text labels except when they help locate adjacent bubble groups.\n"
        "Do not decide whether a bubble is filled. Only return bubble geometry.\n"
        "Schema:\n"
        "{\n"
        '  "svg_width": number | null,\n'
        '  "svg_height": number | null,\n'
        '  "identifier_groups": [\n'
        "    {\n"
        '      "digit_index": integer,\n'
        '      "label": string,\n'
        '      "bubbles": [{"choice": string, "cx": number, "cy": number, "width": number, "height": number}]\n'
        "    }\n"
        "  ],\n"
        '  "problem_groups": [\n'
        "    {\n"
        '      "question_label": string,\n'
        '      "bubbles": [{"choice": string, "cx": number, "cy": number, "width": number, "height": number}]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Preserve logical order: identifier groups left-to-right, problem groups top-to-bottom.\n"
        "- Preserve bubble order inside each group left-to-right or top-to-bottom according to the printed labels.\n"
        "- If labels are numeric or alphabetic, use those exact visible labels for choice.\n"
        "- If unsure about a group, omit it rather than hallucinate.\n"
        "- Output JSON only.\n\n"
        f"SVG summary:\n{svg_summary_json}"
    )


def infer_template_raster_candidates(svg_key: str) -> list[str]:
    path = PurePosixPath(svg_key)
    stem = path.stem
    parent = path.parent
    candidates = [
        str(parent / f"{stem}.jpg"),
        str(parent / f"{stem}.jpeg"),
        str(parent / f"{stem}.png"),
    ]
    return candidates


def resize_for_recognition(image: np.ndarray, max_width: int, explicit_scale: float = 1.0) -> tuple[np.ndarray, float]:
    """Match ProcessorV1 recognition resizing for local tests."""
    height, width = image.shape[:2]
    if 0 < explicit_scale < 1.0:
        resized = cv2.resize(
            image,
            (max(1, int(round(width * explicit_scale))), max(1, int(round(height * explicit_scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, explicit_scale
    if max_width <= 0 or width <= max_width:
        return image, 1.0

    scale = max_width / float(width)
    resized = cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def odd_at_least(value: int, at_least: int = 3) -> int:
    value = max(at_least, int(value))
    return value | 1


def scaled_kernel_size(kernel_size: int, working_width: int, params: ImageProcessingParams) -> int:
    if kernel_size <= 0:
        return 0
    scaled = kernel_size
    if params.adaptive_kernel_scaling and params.reference_template_width > 0:
        scaled = int(round(kernel_size * working_width / float(params.reference_template_width)))
    scaled = max(params.min_morph_kernel_size, scaled)
    return odd_at_least(scaled, at_least=params.min_morph_kernel_size)


def binarize_document(image: np.ndarray, params: ImageProcessingParams) -> np.ndarray:
    if len(image.shape) == 3:
        lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
        gray = lab[:, :, 0]
    else:
        gray = image

    gray = cv2.medianBlur(gray, params.denoise_ksize)

    height, width = gray.shape
    block = odd_at_least(int(min(height, width) * params.adaptive_block_ratio), at_least=params.adaptive_block_min)
    thresh = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=block,
        C=params.adaptive_c,
    )

    close_ksize = scaled_kernel_size(params.morph_close_ksize, width, params)
    open_ksize = scaled_kernel_size(params.morph_open_ksize, width, params)
    morph_ops = (
        [(cv2.MORPH_CLOSE, close_ksize), (cv2.MORPH_OPEN, open_ksize)]
        if params.morph_close_first
        else [(cv2.MORPH_OPEN, open_ksize), (cv2.MORPH_CLOSE, close_ksize)]
    )

    for op, ksize in morph_ops:
        if ksize <= 0:
            continue
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        thresh = cv2.morphologyEx(thresh, op, kernel)

    if params.post_thresh_ksize > 0:
        thresh = cv2.medianBlur(thresh, odd_at_least(params.post_thresh_ksize))

    return thresh


def check_filled_area(image: np.ndarray, template: np.ndarray, params: ImageProcessingParams) -> AreaMetrics:
    inverted = cv2.bitwise_not(image)
    total_area = float(image.shape[0] * image.shape[1])
    if total_area == 0:
        return AreaMetrics(version=1, is_filled=False, fill_ratio=0.0)

    template_inverted = cv2.bitwise_not(template)
    background_pixel_count = float(cv2.countNonZero(template_inverted))
    filled_pixel_count = float(cv2.countNonZero(inverted))
    fill_ratio = max(0.0, filled_pixel_count - background_pixel_count) / total_area
    return AreaMetrics(version=1, is_filled=fill_ratio > params.fill_ratio_threshold, fill_ratio=fill_ratio)


def _scale_bubble(bubble: BubbleSpec, template_width: int, template_height: int, layout: SvgOmrLayout) -> tuple[int, int, int, int]:
    svg_width = layout.svg_width or float(template_width)
    svg_height = layout.svg_height or float(template_height)
    scale_x = template_width / svg_width if svg_width else 1.0
    scale_y = template_height / svg_height if svg_height else 1.0

    width = max(1, int(round(bubble.width * scale_x)))
    height = max(1, int(round(bubble.height * scale_y)))
    x = int(round((bubble.cx - bubble.width / 2.0) * scale_x))
    y = int(round((bubble.cy - bubble.height / 2.0) * scale_y))
    return x, y, width, height


def detect_marked_bubbles(
    warped_thresh: np.ndarray,
    template_thresh: np.ndarray,
    layout: SvgOmrLayout,
    params: ImageProcessingParams,
) -> OMRDetectionResult:
    template_height, template_width = warped_thresh.shape[:2]
    metrics: list[BubbleDetection] = []
    identifier_results: dict[int, list[str]] = {}
    problem_results: dict[str, list[str]] = {}

    for group in layout.identifier_groups:
        detected_choices: list[str] = []
        for bubble in group.bubbles:
            x, y, width, height = _scale_bubble(bubble, template_width, template_height, layout)
            child_region = warped_thresh[y : y + height, x : x + width]
            template_region = template_thresh[y : y + height, x : x + width]
            area_metrics = check_filled_area(child_region, template_region, params)
            if area_metrics["is_filled"]:
                detected_choices.append(bubble.choice)
            metrics.append(
                BubbleDetection(
                    group_type="identifier",
                    group_label=group.label,
                    choice=bubble.choice,
                    is_filled=area_metrics["is_filled"],
                    fill_ratio=float(area_metrics["fill_ratio"]),
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
            )
        identifier_results[group.digit_index] = detected_choices

    for group in layout.problem_groups:
        detected_choices = []
        for bubble in group.bubbles:
            x, y, width, height = _scale_bubble(bubble, template_width, template_height, layout)
            child_region = warped_thresh[y : y + height, x : x + width]
            template_region = template_thresh[y : y + height, x : x + width]
            area_metrics = check_filled_area(child_region, template_region, params)
            if area_metrics["is_filled"]:
                detected_choices.append(bubble.choice)
            metrics.append(
                BubbleDetection(
                    group_type="problem",
                    group_label=group.question_label,
                    choice=bubble.choice,
                    is_filled=area_metrics["is_filled"],
                    fill_ratio=float(area_metrics["fill_ratio"]),
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
            )
        problem_results[group.question_label] = detected_choices

    return OMRDetectionResult(
        identifier_results=identifier_results,
        problem_results=problem_results,
        metrics=metrics,
    )


def annotate_layout(image: np.ndarray, layout: SvgOmrLayout, *, color_identifier: tuple[int, int, int] = (0, 255, 0), color_problem: tuple[int, int, int] = (255, 165, 0)) -> np.ndarray:
    annotated = image.copy()
    image_height, image_width = annotated.shape[:2]

    for group in layout.identifier_groups:
        for bubble in group.bubbles:
            x, y, width, height = _scale_bubble(bubble, image_width, image_height, layout)
            cv2.rectangle(annotated, (x, y), (x + width, y + height), color_identifier, 2)
            cv2.putText(annotated, f"I{group.digit_index}:{bubble.choice}", (x, max(0, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_identifier, 1, cv2.LINE_AA)

    for group in layout.problem_groups:
        for bubble in group.bubbles:
            x, y, width, height = _scale_bubble(bubble, image_width, image_height, layout)
            cv2.rectangle(annotated, (x, y), (x + width, y + height), color_problem, 2)
            cv2.putText(annotated, f"Q{group.question_label}:{bubble.choice}", (x, max(0, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_problem, 1, cv2.LINE_AA)

    return annotated
