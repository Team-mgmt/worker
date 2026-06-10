"""Tests for worker.util module."""

import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

from worker.types import ProcessError
from worker.util import (
    base64url_to_uuid,
    get_barcode_corners,
    is_valid_student_id,
    point_to_tuple,
    prepare_image,
    render_qrcode_on_template,
    uuid_to_base64url,
)


class TestBase64urlToUuid:
    def test_roundtrip(self):
        """Convert UUID -> base64url -> UUID and verify roundtrip."""
        import base64

        original = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        # Encode UUID bytes to base64url
        b64 = base64.urlsafe_b64encode(original.bytes).decode().rstrip("=")
        result = base64url_to_uuid(b64)
        assert result == original

    def test_22_char_string(self):
        """Standard UUID base64url encoding produces 22 chars."""
        import base64

        uid = uuid.uuid4()
        b64 = base64.urlsafe_b64encode(uid.bytes).decode().rstrip("=")
        assert len(b64) == 22
        assert base64url_to_uuid(b64) == uid

    def test_multiple_uuids(self):
        import base64

        for _ in range(10):
            uid = uuid.uuid4()
            b64 = base64.urlsafe_b64encode(uid.bytes).decode().rstrip("=")
            assert base64url_to_uuid(b64) == uid


class TestUuidToBase64Url:
    def test_produces_22_char_unpadded_string(self):
        uid = uuid.uuid4()
        encoded = uuid_to_base64url(uid)
        assert len(encoded) == 22
        assert "=" not in encoded
        assert "+" not in encoded and "/" not in encoded

    def test_roundtrip_with_decoder(self):
        for _ in range(10):
            uid = uuid.uuid4()
            assert base64url_to_uuid(uuid_to_base64url(uid)) == uid

    def test_matches_qmr_web_encoding_for_fixed_uuid(self):
        """Sanity-check against a known UUID so any future regression in the
        encoder is caught (cross-checked against shelfalign-web's `uuidToBase64Url`)."""
        # shelfalign-web: Buffer.from(hex, "hex").toString("base64url") where hex is
        # the UUID with dashes stripped. For this UUID the result is the
        # standard urlsafe base64 of its 16-byte big-endian form, unpadded.
        uid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        # Hand-verified: bytes are 55 0e 84 00 e2 9b 41 d4 a7 16 44 66 55 44 00 00
        # urlsafe_b64encode → "VQ6EAOKbQdSnFkRmVUQAAA==" → strip "==" → "VQ6EAOKbQdSnFkRmVUQAAA"
        assert uuid_to_base64url(uid) == "VQ6EAOKbQdSnFkRmVUQAAA"


class TestIsValidStudentId:
    def test_valid_ids(self):
        assert is_valid_student_id("23456") is True
        assert is_valid_student_id("9") is True
        assert is_valid_student_id("abc123") is True

    def test_empty_string(self):
        assert is_valid_student_id("") is False

    def test_blank_underscore(self):
        assert is_valid_student_id("123_456") is False
        assert is_valid_student_id("_") is False

    def test_multiple_selection_asterisk(self):
        assert is_valid_student_id("123*456") is False
        assert is_valid_student_id("*") is False

    def test_mixed_invalid(self):
        assert is_valid_student_id("_*") is False
        assert is_valid_student_id("12_3*") is False

    def test_starts_with_zero_or_one(self):
        assert is_valid_student_id("0") is False
        assert is_valid_student_id("1") is False
        assert is_valid_student_id("01234") is False
        assert is_valid_student_id("12345") is False


class TestPointToTuple:
    def test_converts_point(self):
        point = MagicMock()
        point.x = 10.5
        point.y = 20.3
        result = point_to_tuple(point)
        assert result == (10.5, 20.3)

    def test_integer_coords(self):
        point = MagicMock()
        point.x = 5
        point.y = 10
        result = point_to_tuple(point)
        assert result == (5.0, 10.0)


class TestGetBarcodeCorners:
    @pytest.fixture
    def mock_barcode(self):
        barcode = MagicMock()
        barcode.position.top_left = MagicMock(x=0.0, y=0.0)
        barcode.position.top_right = MagicMock(x=100.0, y=0.0)
        barcode.position.bottom_right = MagicMock(x=100.0, y=100.0)
        barcode.position.bottom_left = MagicMock(x=0.0, y=100.0)
        return barcode

    def test_lt(self, mock_barcode):
        assert get_barcode_corners(mock_barcode, "LT") == (0.0, 0.0)

    def test_rt(self, mock_barcode):
        assert get_barcode_corners(mock_barcode, "RT") == (100.0, 0.0)

    def test_rb(self, mock_barcode):
        assert get_barcode_corners(mock_barcode, "RB") == (100.0, 100.0)

    def test_lb(self, mock_barcode):
        assert get_barcode_corners(mock_barcode, "LB") == (0.0, 100.0)


class TestRenderQrcodeOnTemplate:
    def _make_qr_image_mock(self, size):
        """Create a mock that behaves like a zxingcpp Image for np.array()."""
        qr_data = np.zeros(size, dtype=np.uint8)
        qr_img = MagicMock()
        qr_img.__array__ = lambda self, dtype=None, copy=None: qr_data
        return qr_img

    def test_uses_zxing_3_to_image_signature(self):
        class StrictNewApiBarcode:
            def __init__(self, qr_image):
                self.qr_image = qr_image
                self.called = False

            def to_image(self, *, scale=1, add_hrt=False, add_quiet_zones=True):
                self.called = True
                assert scale == 1
                assert add_hrt is False
                assert add_quiet_zones is False
                return self.qr_image

        template = np.full((100, 100, 3), 255, dtype=np.uint8)
        barcode = StrictNewApiBarcode(self._make_qr_image_mock((21, 21)))

        result = render_qrcode_on_template(template, barcode, 0, 0, 50, 50)

        assert barcode.called is True
        assert result.shape == (100, 100, 3)

    def test_falls_back_to_zxing_2_to_image_signature(self):
        class StrictOldApiBarcode:
            def __init__(self, qr_image):
                self.qr_image = qr_image
                self.new_signature_attempted = False
                self.old_signature_called = False

            def to_image(self, **kwargs):
                if "scale" in kwargs:
                    self.new_signature_attempted = True
                    raise TypeError("incompatible function arguments")

                self.old_signature_called = True
                assert kwargs == {"size_hint": 50, "with_hrt": False, "with_quiet_zones": False}
                return self.qr_image

        template = np.full((100, 100, 3), 255, dtype=np.uint8)
        barcode = StrictOldApiBarcode(self._make_qr_image_mock((50, 50)))

        result = render_qrcode_on_template(template, barcode, 0, 0, 50, 50)

        assert barcode.new_signature_attempted is True
        assert barcode.old_signature_called is True
        assert result.shape == (100, 100, 3)

    def test_renders_qr_on_template(self):
        template = np.full((200, 200, 3), 255, dtype=np.uint8)
        barcode = MagicMock()
        barcode.to_image.return_value = self._make_qr_image_mock((50, 50))

        result = render_qrcode_on_template(template, barcode, 10, 10, 50, 50)
        assert result.shape == (200, 200, 3)
        # Original should not be modified
        assert np.all(template == 255)

    def test_clips_to_bounds(self):
        template = np.full((50, 50, 3), 255, dtype=np.uint8)
        barcode = MagicMock()
        barcode.to_image.return_value = self._make_qr_image_mock((100, 100))

        # Position extends beyond template bounds
        result = render_qrcode_on_template(template, barcode, 30, 30, 100, 100)
        assert result.shape == (50, 50, 3)


class TestPrepareImage:
    async def test_downloads_from_s3_when_not_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a real image file for cv2 to read
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            img_path = os.path.join(tmpdir, "test.png")
            cv2.imwrite(img_path, img)
            img_bytes = open(img_path, "rb").read()

            # Mock S3 client
            body_mock = AsyncMock()
            body_mock.read = AsyncMock(return_value=img_bytes)
            mock_client = AsyncMock()
            mock_client.get_object = AsyncMock(return_value={"Body": body_mock})

            image_id = uuid.uuid4()
            with patch("worker.util.IMAGES_DIR", tmpdir):
                image, source_scale = await prepare_image(
                    mock_client, "test-bucket", image_id, "path/to/image.png", "images"
                )

            assert image is not None
            assert image.shape[2] == 3  # RGB
            assert source_scale == 1.0  # raster sources never upscale
            mock_client.get_object.assert_called_once()

    async def test_uses_cache_when_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_id = uuid.uuid4()
            # Pre-create the cached image
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            cached_path = os.path.join(tmpdir, f"{image_id}.png")
            cv2.imwrite(cached_path, img)

            mock_client = AsyncMock()

            with patch("worker.util.IMAGES_DIR", tmpdir):
                image, source_scale = await prepare_image(
                    mock_client, "test-bucket", image_id, "path/to/image.png", "images"
                )

            assert image is not None
            assert source_scale == 1.0
            mock_client.get_object.assert_not_called()

    async def test_templates_use_templates_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_id = uuid.uuid4()
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            cached_path = os.path.join(tmpdir, f"{image_id}.png")
            cv2.imwrite(cached_path, img)

            mock_client = AsyncMock()

            with patch("worker.util.TEMPLATES_DIR", tmpdir):
                image, source_scale = await prepare_image(
                    mock_client, "test-bucket", image_id, "path/to/template.png", "templates"
                )

            assert image is not None
            assert source_scale == 1.0

    async def test_on_access_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_id = uuid.uuid4()
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            cached_path = os.path.join(tmpdir, f"{image_id}.png")
            cv2.imwrite(cached_path, img)

            mock_client = AsyncMock()
            callback = MagicMock()

            with patch("worker.util.IMAGES_DIR", tmpdir):
                await prepare_image(
                    mock_client, "test-bucket", image_id, "path/to/image.png", "images",
                    on_access=callback,
                )

            callback.assert_called_once_with(cached_path)

    async def test_raises_on_invalid_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_id = uuid.uuid4()
            # Create an invalid image file (just text)
            bad_path = os.path.join(tmpdir, f"{image_id}.png")
            with open(bad_path, "w") as f:
                f.write("not an image")

            mock_client = AsyncMock()

            with patch("worker.util.IMAGES_DIR", tmpdir):
                with pytest.raises(ProcessError, match="Failed to read image"):
                    await prepare_image(
                        mock_client, "test-bucket", image_id, "path/to/image.png", "images"
                    )

    # Default min-render-width for SVG tests; mirrors the
    # ``ImageProcessingParams.svg_min_render_width`` default and lets each
    # test reason about expected output dims without re-importing it.
    TEST_SVG_MIN_RENDER_WIDTH = 2400

    async def _run_prepare_svg(self, svg_bytes: bytes, svg_min_render_width: int | None = None):
        """Helper: invoke ``prepare_image`` with a mocked S3 returning the SVG.

        First S3 call returns the SVG body; the second (PNG cache lookup)
        misses so the rasterization path is exercised. ``svg_min_render_width``
        falls back to ``TEST_SVG_MIN_RENDER_WIDTH`` so most tests can omit it.
        """
        from pathlib import Path

        if svg_min_render_width is None:
            svg_min_render_width = self.TEST_SVG_MIN_RENDER_WIDTH

        with tempfile.TemporaryDirectory() as cache_root:
            svg_dir = Path(cache_root) / "svg_png"
            svg_dir.mkdir(parents=True)

            body_mock = AsyncMock()
            body_mock.read = AsyncMock(return_value=svg_bytes)

            import botocore.exceptions
            mock_client = AsyncMock()
            cache_miss = botocore.exceptions.ClientError(
                {"Error": {"Code": "NoSuchKey"}}, "GetObject"
            )
            mock_client.get_object = AsyncMock(
                side_effect=[{"Body": body_mock}, cache_miss]
            )
            mock_client.put_object = AsyncMock()

            with patch("worker.util.svg_png_path", lambda d: svg_dir / f"{d}.png"):
                return await prepare_image(
                    mock_client,
                    "test-bucket",
                    uuid.uuid4(),
                    "tpl.svg",
                    "templates",
                    svg_min_render_width=svg_min_render_width,
                )

    async def test_svg_oversized_dimensions_rejected(self):
        """A pathological SVG must be rejected before cairosvg allocates the
        full pixel buffer; otherwise we'd OOM the worker for any malicious
        ``width``/``height`` upload.
        """
        # 50000 x 50000 = 2.5 GP, well past the 16 MP cap.
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'width="50000" height="50000" viewBox="0 0 50000 50000">'
            b'<rect width="50000" height="50000" fill="white"/></svg>'
        )

        with pytest.raises(ProcessError) as exc_info:
            await self._run_prepare_svg(svg_bytes)
        assert exc_info.value.code == "SVG_TOO_LARGE"

    async def test_svg_indeterminate_dimensions_rejected(self):
        """SVGs with neither dimensions nor viewBox can't be sized safely; reject them."""
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<rect width="100" height="100" fill="white"/></svg>'
        )

        with pytest.raises(ProcessError) as exc_info:
            await self._run_prepare_svg(svg_bytes)
        assert exc_info.value.code == "SVG_DIMENSIONS_INDETERMINATE"

    async def test_svg_comma_separated_viewbox_accepted(self):
        """SVG spec allows comma separators in viewBox; previously these were
        rejected as indeterminate because the validator only split on whitespace.
        """
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,640,480">'
            b'<rect width="640" height="480" fill="white"/></svg>'
        )

        image, scale = await self._run_prepare_svg(svg_bytes)
        # 640-wide source is below the helper's default
        # ``svg_min_render_width``, so the rasterizer upscales while
        # preserving aspect. Output dims are ``int(640 * scale)`` ×
        # ``int(480 * scale)`` (cv2: H, W, C); the resolver truncates to
        # guarantee the pixel cap is never exceeded.
        assert scale > 1.0
        assert image.shape[1] == int(640 * scale)
        assert image.shape[0] == int(480 * scale)
        # Aspect ratio preserved within rounding tolerance.
        assert abs(image.shape[1] / image.shape[0] - 640 / 480) < 0.01

    async def test_svg_aspect_ratio_used_for_missing_dimension(self):
        """When only one of width/height is given, the missing side must be
        derived from viewBox aspect ratio (not copied verbatim from viewBox).
        Example from Codex: ``height="100" viewBox="0 0 100000 1"`` renders
        to 10_000_000 × 100 = 1B px in cairosvg; the previous code copied
        ``vb_w=100000`` directly, computed 10 MP, and let it through the cap.
        """
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'height="100" viewBox="0 0 100000 1">'
            b'<rect width="100" height="100" fill="white"/></svg>'
        )

        with pytest.raises(ProcessError) as exc_info:
            await self._run_prepare_svg(svg_bytes)
        assert exc_info.value.code == "SVG_TOO_LARGE"

    async def test_svg_css_number_forms_accepted(self):
        """Length parser must accept the full CSS/SVG numeric grammar — `.5`,
        `1.`, `+10` — instead of rejecting valid templates as
        `SVG_DIMENSIONS_INDETERMINATE` because of an overly strict regex.
        """
        # `.5in` × `+10mm` is ~0.018 MP, well within the cap.
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'width=".5in" height="+10mm">'
            b'<rect width="10" height="10" fill="white"/></svg>'
        )

        image, _ = await self._run_prepare_svg(svg_bytes)
        # Just assert it rasterized; exact dims depend on cairosvg rounding.
        assert image.shape[2] == 3  # RGB
        assert image.shape[0] > 0 and image.shape[1] > 0

    async def test_svg_infinite_length_rejected_cleanly(self):
        """Numerically-extreme widths (e.g. ``1e309`` → ``inf``) used to slip
        past the unit parser and crash with ``OverflowError`` at ``int(width *
        height)``. The validator must convert them into ``ProcessError`` so
        the failure mode stays observable as a normal rejection.
        """
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'width="1e309" height="100">'
            b'<rect width="100" height="100" fill="white"/></svg>'
        )

        with pytest.raises(ProcessError) as exc_info:
            await self._run_prepare_svg(svg_bytes)
        assert exc_info.value.code == "SVG_DIMENSIONS_INDETERMINATE"

    async def test_svg_renders_at_intrinsic_when_above_min_width(self):
        """SVGs whose intrinsic width is at or above the requested
        ``svg_min_render_width`` rasterize at their declared dimensions
        (scale=1.0). This preserves the prior behavior for already-large
        templates: there is no benefit to upscaling, and rasterizing at
        intrinsic minimizes pixel-buffer cost.
        """
        # Choose an intrinsic width >= the configured minimum so no upscale
        # is applied. Height kept short so total pixels stay safely under
        # the cap.
        w = self.TEST_SVG_MIN_RENDER_WIDTH
        h = 100
        svg_bytes = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'</svg>'
        ).encode()

        image, scale = await self._run_prepare_svg(svg_bytes)

        assert scale == 1.0
        # cv2 returns (height, width, channels)
        assert image.shape[:2] == (h, w)

    async def test_svg_upscales_below_min_width(self):
        """Small SVGs are rasterized at higher resolution so OMR detection
        bubbles get enough pixels to be noise-robust. The returned scale is
        the user-unit→raster-pixel multiplier and must be propagated by the
        caller into recognition_scale so area coordinates (in SVG user units)
        translate to correct recognition pixels.
        """
        # Pick a width well below MIN to force upscaling.
        w = max(1, self.TEST_SVG_MIN_RENDER_WIDTH // 4)
        h = max(1, w * 4 // 3)  # 4:3 portrait-ish
        svg_bytes = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'</svg>'
        ).encode()

        image, scale = await self._run_prepare_svg(svg_bytes)

        # Output width hits the minimum; aspect ratio preserved.
        assert image.shape[1] == self.TEST_SVG_MIN_RENDER_WIDTH
        assert abs(scale - self.TEST_SVG_MIN_RENDER_WIDTH / w) < 1e-6
        assert abs(image.shape[1] / image.shape[0] - w / h) < 0.01

    async def test_svg_upscale_respects_caller_min_width(self):
        """``svg_min_render_width`` is a per-request knob: a caller passing
        a different value must get a correspondingly different raster size.
        Same SVG bytes + same code path, but the dimension target is what
        ``ImageProcessingParams`` says, not a baked-in module constant.
        """
        # 600-wide SVG; target a non-default min so a regression that hard-
        # codes the value would not match.
        w = 600
        h = 400
        custom_min = 1800
        svg_bytes = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'</svg>'
        ).encode()

        image, scale = await self._run_prepare_svg(svg_bytes, svg_min_render_width=custom_min)

        assert image.shape[1] == custom_min
        assert abs(scale - custom_min / w) < 1e-6

    async def test_svg_upscale_clamped_by_pixel_cap(self):
        """An SVG that is small in width but tall enough that full upscaling
        would overflow the pixel cap must instead be rasterized at the
        largest factor that fits — preferring graceful degradation over
        outright rejection (intrinsic was already accepted).
        """
        from worker.util import SVG_MAX_INTRINSIC_PIXELS

        # Intrinsic dims are well under the cap and well under cairo's
        # per-axis surface-size limit, but the full ``MIN/w`` upscale would
        # exceed the cap. Concretely with MIN=2400: 400×4000 intrinsic =
        # 1.6 MP; full upscale to (2400, 24000) = 57.6 MP (over cap). The
        # resolver must clamp the factor instead of rejecting.
        w = 400
        h = 4000
        min_w = self.TEST_SVG_MIN_RENDER_WIDTH
        assert w * h < SVG_MAX_INTRINSIC_PIXELS, "intrinsic must fit cap"
        assert min_w * (h * min_w / w) > SVG_MAX_INTRINSIC_PIXELS, (
            "upscale-to-MIN must exceed cap for this test to mean anything"
        )
        svg_bytes = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'</svg>'
        ).encode()

        image, scale = await self._run_prepare_svg(svg_bytes)

        # Final pixel area must respect the cap.
        assert image.shape[0] * image.shape[1] <= SVG_MAX_INTRINSIC_PIXELS
        # Some upscale was applied (the SVG is below MIN width).
        assert scale > 1.0
        # But not the full target factor — it was clamped down.
        assert scale < min_w / w

    async def test_svg_without_min_render_width_raises(self):
        """``prepare_image`` must surface a clear configuration error when
        an SVG source is requested but the caller forgot to pass
        ``svg_min_render_width``. Silently picking a default would let
        mis-configured callers ship a different rasterization than what
        their processing params describe.
        """
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'width="600" height="400" viewBox="0 0 600 400">'
            b'<rect width="600" height="400" fill="white"/></svg>'
        )

        from pathlib import Path

        with tempfile.TemporaryDirectory() as cache_root:
            svg_dir = Path(cache_root) / "svg_png"
            svg_dir.mkdir(parents=True)

            body_mock = AsyncMock()
            body_mock.read = AsyncMock(return_value=svg_bytes)
            mock_client = AsyncMock()
            mock_client.get_object = AsyncMock(return_value={"Body": body_mock})

            with patch("worker.util.svg_png_path", lambda d: svg_dir / f"{d}.png"):
                with pytest.raises(ProcessError) as exc_info:
                    await prepare_image(
                        mock_client,
                        "test-bucket",
                        uuid.uuid4(),
                        "tpl.svg",
                        "templates",
                    )

        assert exc_info.value.code == "SVG_RENDER_CONFIG_MISSING"
