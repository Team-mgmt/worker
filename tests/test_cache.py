"""Tests for worker.cache module."""

import datetime
import tempfile
from unittest.mock import patch
from uuid import UUID

import numpy as np

from worker import cache
from worker.types import ImageProcessingParams


EXAM_PAPER_ID = UUID("12345678-1234-5678-1234-567812345678")
OTHER_EXAM_PAPER_ID = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
EXAM_ID = UUID("11111111-2222-3333-4444-555555555555")
OTHER_EXAM_ID = UUID("99999999-8888-7777-6666-555555555555")
EXAM_ROUND_ID = UUID("aaaa1111-aaaa-2222-aaaa-333333333333")
OTHER_EXAM_ROUND_ID = UUID("bbbb1111-bbbb-2222-bbbb-333333333333")
EXAM_PAPER_UPDATED_AT = datetime.datetime(2026, 5, 1, 12, 0, 0)
OTHER_EXAM_PAPER_UPDATED_AT = datetime.datetime(2026, 5, 2, 12, 0, 0)
EXAM_UPDATED_AT = datetime.datetime(2026, 5, 3, 12, 0, 0)
OTHER_EXAM_UPDATED_AT = datetime.datetime(2026, 5, 4, 12, 0, 0)
EXAM_ROUND_UPDATED_AT = datetime.datetime(2026, 5, 5, 12, 0, 0)
OTHER_EXAM_ROUND_UPDATED_AT = datetime.datetime(2026, 5, 6, 12, 0, 0)


def _binary_image(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, (120, 80), dtype=np.uint8)
    return bits * 255


# Shorthand keyword args so tests stay readable.
_DEFAULT_KEY: dict = dict(
    exam_paper_id=EXAM_PAPER_ID,
    exam_paper_updated_at=EXAM_PAPER_UPDATED_AT,
    exam_id=EXAM_ID,
    exam_updated_at=EXAM_UPDATED_AT,
    exam_round_id=EXAM_ROUND_ID,
    exam_round_updated_at=EXAM_ROUND_UPDATED_AT,
    background_image="bg.png",
)


class TestTemplateThreshCache:
    def test_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                result = cache.get_template_thresh(**_DEFAULT_KEY, params=params)
                assert result is None

    def test_put_then_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=1)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                loaded = cache.get_template_thresh(**_DEFAULT_KEY, params=params)

                assert loaded is not None
                assert loaded.shape == image.shape
                assert loaded.dtype == np.uint8
                np.testing.assert_array_equal(loaded, image)

    def test_different_exam_paper_ids_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_paper_id": OTHER_EXAM_PAPER_ID}, params=params
                )

                assert result is None

    def test_different_exam_paper_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_paper_updated_at": OTHER_EXAM_PAPER_UPDATED_AT},
                    params=params,
                )

                assert result is None

    def test_different_exam_id_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_id": OTHER_EXAM_ID}, params=params
                )

                assert result is None

    def test_different_exam_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_updated_at": OTHER_EXAM_UPDATED_AT}, params=params
                )

                assert result is None

    def test_different_exam_round_id_is_isolated(self):
        """Two rounds under the same exam render different {EXAM_ROUND_NAME}
        text, so they must not share a cached binarized template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_round_id": OTHER_EXAM_ROUND_ID}, params=params
                )

                assert result is None

    def test_different_exam_round_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=2)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=image)
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "exam_round_updated_at": OTHER_EXAM_ROUND_UPDATED_AT},
                    params=params,
                )

                assert result is None

    def test_different_background_image_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                image = _binary_image(seed=3)

                cache.put_template_thresh(
                    **{**_DEFAULT_KEY, "background_image": "bg-a.png"}, params=params, image=image
                )
                result = cache.get_template_thresh(
                    **{**_DEFAULT_KEY, "background_image": "bg-b.png"}, params=params
                )

                assert result is None

    def test_different_params_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(adaptive_c=7)
                params_b = ImageProcessingParams(adaptive_c=9)
                image = _binary_image(seed=4)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params_a, image=image)
                result = cache.get_template_thresh(**_DEFAULT_KEY, params=params_b)

                assert result is None

    def test_different_svg_min_render_width_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(svg_min_render_width=2400)
                params_b = ImageProcessingParams(svg_min_render_width=3200)
                image = _binary_image(seed=7)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params_a, image=image)
                result = cache.get_template_thresh(**_DEFAULT_KEY, params=params_b)

                assert result is None

    def test_same_svg_min_render_width_hits_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(svg_min_render_width=2400)
                params_b = ImageProcessingParams(svg_min_render_width=2400)
                image = _binary_image(seed=8)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params_a, image=image)
                loaded = cache.get_template_thresh(**_DEFAULT_KEY, params=params_b)

                assert loaded is not None
                np.testing.assert_array_equal(loaded, image)

    def test_put_overwrites_existing_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                first = _binary_image(seed=5)
                second = _binary_image(seed=6)

                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=first)
                cache.put_template_thresh(**_DEFAULT_KEY, params=params, image=second)
                loaded = cache.get_template_thresh(**_DEFAULT_KEY, params=params)

                assert loaded is not None
                np.testing.assert_array_equal(loaded, second)


def _make_area(area_id: str, pos_x: float = 0.0, pos_y: float = 0.0, children: dict | None = None):
    """Build a duck-typed area object for cache-key tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=UUID(area_id),
        pos_x=pos_x,
        pos_y=pos_y,
        width=100.0,
        height=100.0,
        data={"children": children or {}},
    )


class TestTemplateBaselineFillMapCache:
    def test_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas
                )
                assert result is None

    def test_put_then_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                fill_map = {"area-a:1": 0.125, "area-a:2": 0.875}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas, fill_map=fill_map
                )
                loaded = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas
                )

                assert loaded == fill_map

    def test_different_background_image_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "background_image": "bg-a.png"},
                    params=params,
                    areas=areas,
                    fill_map={"area-a:1": 0.1},
                )

                result = cache.get_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "background_image": "bg-b.png"},
                    params=params,
                    areas=areas,
                )
                assert result is None

    def test_different_exam_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "exam_updated_at": OTHER_EXAM_UPDATED_AT},
                    params=params,
                    areas=areas,
                )
                assert result is None

    def test_different_exam_paper_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "exam_paper_updated_at": OTHER_EXAM_PAPER_UPDATED_AT},
                    params=params,
                    areas=areas,
                )
                assert result is None

    def test_different_exam_round_id_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "exam_round_id": OTHER_EXAM_ROUND_ID},
                    params=params,
                    areas=areas,
                )
                assert result is None

    def test_different_exam_round_updated_at_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **{**_DEFAULT_KEY, "exam_round_updated_at": OTHER_EXAM_ROUND_UPDATED_AT},
                    params=params,
                    areas=areas,
                )
                assert result is None

    def test_different_params_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(adaptive_c=7)
                params_b = ImageProcessingParams(adaptive_c=9)
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_a, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_b, areas=areas
                )
                assert result is None

    def test_different_measurement_shape_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(bubble_measurement_shape="ellipse")
                params_b = ImageProcessingParams(bubble_measurement_shape="rect")
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_a, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_b, areas=areas
                )
                assert result is None

    def test_different_roi_morphology_order_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(bubble_roi_use_morphology=True, bubble_roi_morph_close_first=True)
                params_b = ImageProcessingParams(bubble_roi_use_morphology=True, bubble_roi_morph_close_first=False)
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_a, areas=areas, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_b, areas=areas
                )
                assert result is None

    def test_unrelated_params_do_not_invalidate_baseline_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params_a = ImageProcessingParams(annotation_thickness=2, fill_ratio_threshold=0.4)
                params_b = ImageProcessingParams(annotation_thickness=9, fill_ratio_threshold=0.9)
                areas = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")]
                fill_map = {"area-a:1": 0.1}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_a, areas=areas, fill_map=fill_map
                )
                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params_b, areas=areas
                )

                assert result == fill_map

    def test_changed_area_position_invalidates_baseline_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas_a = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pos_x=10.0, pos_y=10.0)]
                areas_b = [_make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pos_x=20.0, pos_y=10.0)]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_a, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_b
                )
                assert result is None

    def test_changed_children_layout_invalidates_baseline_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                areas_a = [_make_area(
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    children={"1": {"pos_x": 0, "pos_y": 0, "width": 10, "height": 10}},
                )]
                areas_b = [_make_area(
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    children={"1": {"pos_x": 5, "pos_y": 0, "width": 10, "height": 10}},
                )]
                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_a, fill_map={"area-a:1": 0.1}
                )

                result = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_b
                )
                assert result is None

    def test_identical_layout_via_distinct_area_instances_hits_cache(self):
        """Positive branch: same layout values on different objects must hit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                children = {"1": {"pos_x": 0, "pos_y": 0, "width": 10, "height": 10}}
                areas_write = [_make_area(
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pos_x=10.0, pos_y=20.0, children=dict(children),
                )]
                areas_read = [_make_area(
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pos_x=10.0, pos_y=20.0, children=dict(children),
                )]
                fill_map = {"area-a:1": 0.42}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_write, fill_map=fill_map
                )
                loaded = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=areas_read
                )

                assert loaded == fill_map

    def test_area_input_order_does_not_affect_cache_key(self):
        """Layout digest sorts by area id, so input order must not change the key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                area_a = _make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pos_x=1.0)
                area_b = _make_area("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", pos_x=2.0)
                fill_map = {"area-a:1": 0.1, "area-b:1": 0.2}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_a, area_b], fill_map=fill_map
                )
                loaded = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_b, area_a]
                )

                assert loaded == fill_map

    def test_non_dict_area_data_falls_back_to_empty_children(self):
        """isinstance(area.data, dict) False branch: non-dict data must not crash and must key stably."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                area_none = _make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
                area_none.data = None
                area_list = _make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
                area_list.data = []
                fill_map = {"area-a:1": 0.5}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_none], fill_map=fill_map
                )
                # Both non-dict shapes resolve to the same empty-children digest.
                loaded = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_list]
                )

                assert loaded == fill_map

    def test_missing_children_key_in_dict_data_hits_same_entry_as_empty_children(self):
        """data.get('children', {}) default branch — absent key matches the empty-dict layout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cache, "CACHE_DIR", tmpdir):
                params = ImageProcessingParams()
                area_empty = _make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", children={})
                area_no_key = _make_area("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
                area_no_key.data = {"other": "value"}
                fill_map = {"area-a:1": 0.3}

                cache.put_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_empty], fill_map=fill_map
                )
                loaded = cache.get_template_baseline_fill_map(
                    **_DEFAULT_KEY, params=params, areas=[area_no_key]
                )

                assert loaded == fill_map
