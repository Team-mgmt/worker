"""Tests for worker.processors registry."""

import pytest

from worker.processors import PROCESSORS, get_processor
from worker.processors.base import BaseProcessor
from worker.processors.v1 import ProcessorV1


class TestProcessorRegistry:
    def test_registry_contains_v1(self):
        assert 1.0 in PROCESSORS
        assert PROCESSORS[1.0] is ProcessorV1

    def test_get_processor_v1(self):
        cls = get_processor(1.0)
        assert cls is ProcessorV1

    def test_get_processor_invalid_version(self):
        with pytest.raises(ValueError, match="Unsupported processor version: 99.0"):
            get_processor(99.0)

    def test_get_processor_returns_subclass_of_base(self):
        cls = get_processor(1.0)
        assert issubclass(cls, BaseProcessor)
