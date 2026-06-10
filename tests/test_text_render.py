"""Tests for worker.text_render."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import numpy as np
import pytest
from PIL import ImageFont

from worker.generated.models import Exampaperareabasetype
from worker.text_render import (
    _font_size_overrides_from_exam_metadata,
    _format_exam_name,
    _substitute_text_variables,
    render_text_areas_on_template,
)
from worker.util import uuid_to_base64url


def test_substitute_text_variables_replaces_all_known_placeholders():
    out = _substitute_text_variables(
        "{EXAM_NAME} | {EXAM_TITLE} | {EXAM_YEAR} | {EXAM_ROUND_NAME} | {EXAM_ROUND_NUMBER} | {EXAM_ID}",
        exam_name="2027 3월",
        exam_title="3월",
        exam_year="2027",
        exam_round_name="기본",
        exam_round_number="32회",
        exam_id_b64="abc",
    )
    assert "2027 3월" in out
    assert "3월" in out
    assert "2027" in out
    assert "기본" in out
    assert "32회" in out
    assert "abc" in out
    assert "{EXAM_" not in out  # all placeholders consumed


def test_substitute_text_variables_eats_trailing_회_after_round_number():
    # Older templates literally append `회` after the placeholder; the
    # substitution already expands to `<n>회`, so the trailing literal must
    # collapse rather than double up.
    out = _substitute_text_variables(
        "{EXAM_ROUND_NUMBER}회",
        exam_name="",
        exam_title="",
        exam_year="",
        exam_round_name="",
        exam_round_number="32회",
        exam_id_b64="",
    )
    assert out == "32회"


def test_format_exam_name_joins_non_empty_parts():
    exam = SimpleNamespace(year="2027", title="3월", round_number=32)
    assert _format_exam_name(exam) == "2027 3월 32회"


def test_format_exam_name_skips_empty_year_and_null_round():
    exam = SimpleNamespace(year="", title="모의", round_number=None)
    assert _format_exam_name(exam) == "모의"


def _text_area(text_content: str | None = "{EXAM_TITLE}", **overrides):
    area_type = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        base_type=Exampaperareabasetype.TEXT,
        data={"textContent": text_content} if text_content is not None else {},
    )
    defaults = dict(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        pos_x=10.0,
        pos_y=20.0,
        width=200.0,
        height=40.0,
        data={"fontSize": 20, "fontFamily": "Pretendard", "fontWeight": "normal", "textAlign": "left"},
        index=0,
        area_type=area_type,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _non_text_area():
    area_type = SimpleNamespace(
        id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        base_type=Exampaperareabasetype.PROBLEM,
        data={},
    )
    return SimpleNamespace(
        id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        pos_x=0.0,
        pos_y=0.0,
        width=10.0,
        height=10.0,
        data={"children": {}},
        index=1,
        area_type=area_type,
    )


def _stub_exam():
    return SimpleNamespace(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        title="3월 전국연합학력평가",
        year="2027",
        round_number=32,
        updated_at=datetime.datetime(2026, 5, 1),
    )


def _stub_exam_round():
    return SimpleNamespace(
        id=UUID("66666666-7777-8888-9999-aaaaaaaaaaaa"),
        name="기본 그룹",
        updated_at=datetime.datetime(2026, 5, 1),
    )


async def test_render_skips_when_no_text_areas():
    template = np.full((100, 200, 3), 255, dtype=np.uint8)
    before = template.copy()

    result = await render_text_areas_on_template(
        client=AsyncMock(),
        bucket="any",
        template_image=template,
        areas=[_non_text_area()],
        exam=_stub_exam(),
        exam_round=_stub_exam_round(),
        recognition_scale=1.0,
    )
    assert result == 0
    np.testing.assert_array_equal(template, before)


async def test_render_skips_when_font_unavailable():
    """If S3 has neither the requested font nor Pretendard-Regular, the area is silently skipped."""
    template = np.full((100, 200, 3), 255, dtype=np.uint8)
    before = template.copy()

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=None)):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[_text_area()],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    assert result == 0
    np.testing.assert_array_equal(template, before)


async def test_render_skips_areas_with_empty_text_content():
    template = np.full((100, 200, 3), 255, dtype=np.uint8)
    before = template.copy()

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=b"\x00")):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[_text_area(text_content=None)],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    assert result == 0
    np.testing.assert_array_equal(template, before)


async def test_render_draws_text_when_font_available():
    template = np.full((100, 400, 3), 255, dtype=np.uint8)
    before = template.copy()

    # Load any TrueType present on the system so PIL can actually rasterize.
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    # Inspect the loaded font path: PIL's font_variant retains the same source.
    font_path = font.path

    with open(font_path, "rb") as fh:
        font_bytes = fh.read()

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[_text_area(text_content="Hello")],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=2.0,
        )

    assert result == 1
    # Mutation visible: at least one pixel turned non-white.
    assert (template != before).any()


async def test_render_respects_recognition_scale():
    """Text size and position scale with recognition_scale."""
    template = np.full((200, 800, 3), 255, dtype=np.uint8)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    with open(font.path, "rb") as fh:
        font_bytes = fh.read()

    # area at pos_y=20 with recognition_scale=2.0 → pos_y_px=40
    # area height 40 → 80 in pixels
    area = _text_area(text_content="X")

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)):
        await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[area],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=2.0,
        )

    # Find the darkened y-range: text should sit roughly between y=40 and y=120
    rows_with_ink = np.where((template < 250).any(axis=(1, 2)))[0]
    assert len(rows_with_ink) > 0
    assert rows_with_ink.min() >= 40
    assert rows_with_ink.max() <= 120


async def test_render_substitutes_exam_id_with_base64url_encoded_uuid():
    """{EXAM_ID} must expand to the same base64url encoding shelfalign-web uses,
    so the rendered template text matches what's printed on the paper."""
    template = np.full((100, 800, 3), 255, dtype=np.uint8)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    with open(font.path, "rb") as fh:
        font_bytes = fh.read()

    exam = _stub_exam()
    captured = {}

    def _capturing_substitute(content, **kwargs):
        captured.update(kwargs)
        return content.replace("{EXAM_ID}", kwargs["exam_id_b64"])

    with (
        patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)),
        patch("worker.text_render._substitute_text_variables", side_effect=_capturing_substitute),
    ):
        await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[_text_area(text_content="{EXAM_ID}")],
            exam=exam,
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    assert captured["exam_id_b64"] == uuid_to_base64url(exam.id)
    assert captured["exam_id_b64"]  # non-empty (no longer hardcoded "")


async def test_render_clears_text_area_to_white_background():
    """Each defined TEXT area's bounding box is filled white before drawing,
    so any template ink under the area doesn't leak through into the matcher."""
    # Start with a fully-black template so the white-fill is detectable.
    template = np.zeros((100, 400, 3), dtype=np.uint8)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    with open(font.path, "rb") as fh:
        font_bytes = fh.read()

    # area at (10, 20) size 200x40, recognition_scale=1.0
    area = _text_area(text_content="Hello")

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)):
        await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[area],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    # The interior of the area should now contain plenty of white pixels
    # (background fill), even though the template started fully black. Sample
    # a corner pixel inside the area but away from where text would land.
    assert (template[21:60, 199:209] == 255).all()
    # And outside the area, the original black should remain.
    assert (template[0:10, 0:400] == 0).all()


async def test_render_whites_out_text_area_even_with_empty_content():
    """A TEXT area with no textContent still gets its bounding box cleared to
    white — the area is a declared region, so the template should be blank
    there regardless of whether we draw glyphs on top."""
    template = np.zeros((100, 400, 3), dtype=np.uint8)

    area = _text_area(text_content=None)

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=b"\x00")):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[area],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    # No glyphs drawn, but the white-fill rectangle still ran.
    assert result == 0
    # Area interior is now white.
    assert (template[21:59, 11:209] == 255).all()
    # Outside the area is still black — including the row/column directly
    # past the bottom-right corner (guards against PIL's inclusive-corner
    # off-by-one on ImageDraw.rectangle).
    assert (template[0:10, 0:400] == 0).all()
    assert (template[60, :] == 0).all()
    assert (template[:, 210] == 0).all()


def test_font_size_overrides_from_exam_metadata_parses_v1():
    metadata = {
        "version": "1",
        "template": {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": {"fontSize": 24},
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb": {"fontSize": 18.5},
        },
    }
    out = _font_size_overrides_from_exam_metadata(metadata)
    assert out == {
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": 24.0,
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb": 18.5,
    }


def test_font_size_overrides_returns_empty_when_metadata_missing_or_unrecognized():
    # Wrong version, missing template, non-dict input, etc. — all empty,
    # matching shelfalign-web's safeParse-fails fallback.
    assert _font_size_overrides_from_exam_metadata(None) == {}
    assert _font_size_overrides_from_exam_metadata({}) == {}
    assert _font_size_overrides_from_exam_metadata({"version": "2", "template": {}}) == {}
    assert _font_size_overrides_from_exam_metadata({"version": "1"}) == {}
    assert _font_size_overrides_from_exam_metadata({"version": "1", "template": "nope"}) == {}
    # fontSize must be numeric (not bool, not string).
    assert (
        _font_size_overrides_from_exam_metadata(
            {"version": "1", "template": {"a": {"fontSize": True}}}
        )
        == {}
    )
    assert (
        _font_size_overrides_from_exam_metadata(
            {"version": "1", "template": {"a": {"fontSize": "24"}}}
        )
        == {}
    )
    # Areas without fontSize are simply absent from the override map.
    assert _font_size_overrides_from_exam_metadata({"version": "1", "template": {"a": {}}}) == {}
    # Value not an object → whole payload rejected.
    assert (
        _font_size_overrides_from_exam_metadata({"version": "1", "template": {"a": None}}) == {}
    )


def test_font_size_overrides_rejects_explicit_null_font_size():
    """zod's z.number().optional() rejects explicit null (only missing/
    undefined is valid). The backend's safeParse fails on null and falls
    back to no overrides for every area; the worker must do the same."""
    # Lone null → empty.
    assert (
        _font_size_overrides_from_exam_metadata(
            {"version": "1", "template": {"a": {"fontSize": None}}}
        )
        == {}
    )
    # One numeric override + one explicit-null entry → empty (all-or-nothing).
    assert (
        _font_size_overrides_from_exam_metadata(
            {
                "version": "1",
                "template": {
                    "a": {"fontSize": 24},
                    "b": {"fontSize": None},
                },
            }
        )
        == {}
    )
    # Missing fontSize key remains valid (z.number().optional() accepts
    # undefined) — the area simply has no override and we keep parsing
    # other entries.
    assert (
        _font_size_overrides_from_exam_metadata(
            {
                "version": "1",
                "template": {
                    "a": {"fontSize": 24},
                    "b": {},
                },
            }
        )
        == {"a": 24.0}
    )


def test_font_size_overrides_rejects_entire_payload_on_any_invalid_entry():
    """Mirrors zod safeParse's all-or-nothing semantics: one malformed entry
    causes the backend to drop every override, so the worker must too."""
    # One valid numeric override + one string fontSize → empty.
    assert (
        _font_size_overrides_from_exam_metadata(
            {
                "version": "1",
                "template": {
                    "a": {"fontSize": 24},
                    "b": {"fontSize": "bad"},
                },
            }
        )
        == {}
    )
    # One valid override + one boolean fontSize → empty (booleans aren't numbers in zod).
    assert (
        _font_size_overrides_from_exam_metadata(
            {
                "version": "1",
                "template": {
                    "a": {"fontSize": 24},
                    "b": {"fontSize": True},
                },
            }
        )
        == {}
    )
    # Valid overrides mixed with a non-dict value also poison the whole payload.
    assert (
        _font_size_overrides_from_exam_metadata(
            {
                "version": "1",
                "template": {
                    "a": {"fontSize": 24},
                    "b": "not-a-dict",
                },
            }
        )
        == {}
    )


async def test_render_uses_exam_metadata_font_size_override():
    """Per-area fontSize overrides on exam.metadata.template take precedence
    over area.data.fontSize, mirroring the backend PDF renderer."""
    template = np.full((200, 800, 3), 255, dtype=np.uint8)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    with open(font.path, "rb") as fh:
        font_bytes = fh.read()

    # Two identical areas at different y-positions; one uses the default
    # fontSize from area.data (small), the other gets a much larger override.
    area_default = _text_area(text_content="X")
    area_default.pos_y = 20.0
    area_default.id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    area_default.data = dict(area_default.data, fontSize=8)

    area_override = _text_area(text_content="X")
    area_override.pos_y = 100.0
    area_override.id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    area_override.data = dict(area_override.data, fontSize=8)

    exam = _stub_exam()
    exam.metadata_ = {
        "version": "1",
        "template": {
            str(area_override.id): {"fontSize": 40},
            # Area not in `areas` — must be ignored, not error.
            "11111111-1111-1111-1111-111111111111": {"fontSize": 99},
        },
    }

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[area_default, area_override],
            exam=exam,
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    assert result == 2

    # The override area should produce a taller ink band than the default area.
    def _ink_height(y_top: int, y_bot: int) -> int:
        rows = np.where((template[y_top:y_bot] < 250).any(axis=(1, 2)))[0]
        return int(rows.max() - rows.min() + 1) if len(rows) else 0

    default_h = _ink_height(20, 60)
    override_h = _ink_height(100, 180)
    assert override_h > default_h * 2, f"override {override_h} not noticeably taller than default {default_h}"


async def test_render_handles_invalid_font_size_default():
    template = np.full((100, 400, 3), 255, dtype=np.uint8)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=12)
    except OSError:
        pytest.skip("No TrueType font available in test environment")
    with open(font.path, "rb") as fh:
        font_bytes = fh.read()

    area = _text_area()
    area.data = {"fontSize": "not-a-number"}

    with patch("worker.text_render.fonts.get_font_bytes", AsyncMock(return_value=font_bytes)):
        result = await render_text_areas_on_template(
            client=AsyncMock(),
            bucket="any",
            template_image=template,
            areas=[area],
            exam=_stub_exam(),
            exam_round=_stub_exam_round(),
            recognition_scale=1.0,
        )

    # Falls back to fontSize=16; should still render.
    assert result == 1
