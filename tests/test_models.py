"""Tests for worker.models module."""

import uuid

from worker.models import SoftDeleteMixin, UUIDPrimaryKeyMixin


class TestUUIDPrimaryKeyMixin:
    def test_has_id_column(self):
        assert hasattr(UUIDPrimaryKeyMixin, "id")


class TestSoftDeleteMixin:
    def test_inherits_uuid_mixin(self):
        assert issubclass(SoftDeleteMixin, UUIDPrimaryKeyMixin)

    def test_has_deleted_at_column(self):
        assert hasattr(SoftDeleteMixin, "deleted_at")
