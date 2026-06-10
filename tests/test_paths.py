"""Tests for worker.paths module."""

import os
import tempfile
from unittest.mock import patch
from uuid import UUID

from worker.paths import (
    APP_DIR,
    ASSETS_DIR,
    get_image_path,
    get_request_results_dir,
    get_result_path,
    get_results_dir,
    get_template_path,
    init_storage_dirs,
)


class TestPathConstants:
    def test_app_dir_exists(self):
        assert APP_DIR.exists()

    def test_assets_dir_is_under_app_dir(self):
        assert ASSETS_DIR == APP_DIR / "assets"


class TestGetImagePath:
    def test_returns_correct_path(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        path = get_image_path(uid, ".png")
        assert path.endswith(f"{uid}.png")
        assert "images" in path

    def test_different_extensions(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        assert get_image_path(uid, ".jpg").endswith(".jpg")
        assert get_image_path(uid, ".png").endswith(".png")


class TestGetTemplatePath:
    def test_returns_correct_path(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        path = get_template_path(uid, ".png")
        assert path.endswith(f"{uid}.png")
        assert "templates" in path


class TestGetResultsDir:
    def test_returns_correct_path(self):
        req_id = UUID("12345678-1234-5678-1234-567812345678")
        job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        path = get_results_dir(req_id, job_id)
        assert str(req_id) in path
        assert str(job_id) in path
        assert "results" in path


class TestGetResultPath:
    def test_returns_correct_path(self):
        req_id = UUID("12345678-1234-5678-1234-567812345678")
        job_id = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
        path = get_result_path(req_id, job_id, "threshold.png")
        assert path.endswith("threshold.png")
        assert str(req_id) in path
        assert str(job_id) in path


class TestGetRequestResultsDir:
    def test_returns_correct_path(self):
        req_id = UUID("12345678-1234-5678-1234-567812345678")
        path = get_request_results_dir(req_id)
        assert str(req_id) in path
        assert "results" in path


class TestInitStorageDirs:
    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("worker.paths.IMAGES_DIR", os.path.join(tmpdir, "images")),
                patch("worker.paths.TEMPLATES_DIR", os.path.join(tmpdir, "templates")),
                patch("worker.paths.RESULTS_DIR", os.path.join(tmpdir, "results")),
            ):
                init_storage_dirs()
                assert os.path.isdir(os.path.join(tmpdir, "images"))
                assert os.path.isdir(os.path.join(tmpdir, "templates"))
                assert os.path.isdir(os.path.join(tmpdir, "results"))

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("worker.paths.IMAGES_DIR", os.path.join(tmpdir, "images")),
                patch("worker.paths.TEMPLATES_DIR", os.path.join(tmpdir, "templates")),
                patch("worker.paths.RESULTS_DIR", os.path.join(tmpdir, "results")),
            ):
                init_storage_dirs()
                init_storage_dirs()  # Should not raise
                assert os.path.isdir(os.path.join(tmpdir, "images"))
