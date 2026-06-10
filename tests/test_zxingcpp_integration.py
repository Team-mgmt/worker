"""Integration coverage for the zxing-cpp binding and local type stub."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import zxingcpp

from worker.util import render_qrcode_on_template


def test_render_qrcode_on_template_with_real_zxingcpp_barcode():
    barcode = zxingcpp.create_barcode("https://example.com?a=abc", zxingcpp.BarcodeFormat.QRCode)
    template = np.full((120, 120, 3), 255, dtype=np.uint8)

    result = render_qrcode_on_template(template, barcode, 10, 10, 80, 80)

    assert result.shape == template.shape
    assert result.dtype == np.uint8
    assert np.array_equal(result[:10, :, :], template[:10, :, :])

    rendered_qr = result[10:90, 10:90]
    assert rendered_qr.min() == 0
    assert rendered_qr.max() == 255


def test_zxingcpp_stub_accepts_supported_barcode_render_signatures(tmp_path):
    pytest.importorskip("mypy")

    repo_root = Path(__file__).resolve().parents[1]
    probe = tmp_path / "zxingcpp_stub_probe.py"
    probe.write_text(
        """
from zxingcpp import (
    Barcode,
    BarcodeFormat,
    Image,
    create_barcode,
    write_barcode_to_image,
    write_barcode_to_svg,
)

barcode: Barcode = create_barcode("https://example.com?a=abc", BarcodeFormat.QRCode)

new_image: Image = barcode.to_image(scale=1, add_hrt=False, add_quiet_zones=False)
old_image: Image = barcode.to_image(size_hint=80, with_hrt=False, with_quiet_zones=False)
new_svg: str = barcode.to_svg(scale=1, add_hrt=False, add_quiet_zones=False)
old_svg: str = barcode.to_svg(size_hint=80, with_hrt=False, with_quiet_zones=False)

new_written_image: Image = write_barcode_to_image(
    barcode,
    scale=1,
    add_hrt=False,
    add_quiet_zones=False,
)
old_written_image: Image = write_barcode_to_image(
    barcode,
    size_hint=80,
    with_hrt=False,
    with_quiet_zones=False,
)
new_written_svg: str = write_barcode_to_svg(
    barcode,
    scale=1,
    add_hrt=False,
    add_quiet_zones=False,
)
old_written_svg: str = write_barcode_to_svg(
    barcode,
    size_hint=80,
    with_hrt=False,
    with_quiet_zones=False,
)
""".lstrip(),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["MYPYPATH"] = str(repo_root / "stubs")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(repo_root / "pyproject.toml"),
            "--show-error-codes",
            str(probe),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
