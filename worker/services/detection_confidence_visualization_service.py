from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def _polygon(item: dict) -> list[tuple[float, float]]:
    points = item.get("obb_polygon") or []
    if len(points) == 4:
        return [(float(point[0]), float(point[1])) for point in points]
    bbox = item.get("bbox") or []
    if len(bbox) != 4:
        return []
    left, top, right, bottom = (float(value) for value in bbox)
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def _bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap_over_smaller(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    smaller = min(first_area, second_area)
    return intersection / smaller if smaller else 0.0


def render_confidence_visualization(
    original: bytes,
    result: dict,
    *,
    threshold: float,
    focus_order: int | None = None,
) -> bytes:
    with Image.open(BytesIO(original)) as source:
        image = source.convert("RGB")

    items = [
        item
        for item in result.get("inference", {}).get("results", [])
        if isinstance(item, dict) and _polygon(item)
    ]
    selected = items
    if focus_order is not None:
        focus = next((item for item in items if item.get("detected_order") == focus_order), None)
        if focus is not None:
            focus_bounds = _bounds(_polygon(focus))
            selected = [
                item
                for item in items
                if _overlap_over_smaller(_bounds(_polygon(item)), focus_bounds) >= 0.15
            ]

    if selected:
        all_bounds = [_bounds(_polygon(item)) for item in selected]
        left = min(bound[0] for bound in all_bounds)
        top = min(bound[1] for bound in all_bounds)
        right = max(bound[2] for bound in all_bounds)
        bottom = max(bound[3] for bound in all_bounds)
        padding_x = max(40, round((right - left) * 0.35))
        padding_y = max(40, round((bottom - top) * 0.05))
        crop_box = (
            max(0, round(left - padding_x)),
            max(0, round(top - padding_y)),
            min(image.width, round(right + padding_x)),
            min(image.height, round(bottom + padding_y)),
        )
    else:
        crop_box = (0, 0, image.width, image.height)

    canvas = image.crop(crop_box)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=max(14, round(min(canvas.size) / 35)))
    line_width = max(3, round(min(canvas.size) / 120))

    for item in selected:
        points = [(round(x - crop_box[0]), round(y - crop_box[1])) for x, y in _polygon(item)]
        confidence = float(item.get("detection_confidence") or 0.0)
        kept = confidence >= threshold
        color = "#16a34a" if kept else "#dc2626"
        draw.line([*points, points[0]], fill=color, width=line_width, joint="curve")
        label = (
            f"#{item.get('detected_order', '?')}  conf={confidence:.3f}  "
            f"{'KEEP' if kept else 'DROP'}"
        )
        anchor = min(points, key=lambda point: (point[1], point[0]))
        text_box = draw.textbbox(anchor, label, font=font, stroke_width=1)
        draw.rectangle(text_box, fill=color)
        draw.text(anchor, label, fill="white", font=font, stroke_width=1, stroke_fill=color)

    legend = f"confidence threshold={threshold:.2f}   GREEN=KEEP   RED=DROP"
    legend_box = draw.textbbox((12, 12), legend, font=font, stroke_width=1)
    draw.rectangle(legend_box, fill="#111827")
    draw.text((12, 12), legend, fill="white", font=font, stroke_width=1, stroke_fill="#111827")

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()
