"""Tests for worker.profiler module."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from worker.profiler import JobProfiler, TimingResult


class TestTimingResult:
    def test_creation(self):
        tr = TimingResult(name="step1", duration_ms=123.4)
        assert tr.name == "step1"
        assert tr.duration_ms == 123.4


class TestJobProfiler:
    def test_empty_profiler(self):
        profiler = JobProfiler()
        assert profiler.total_ms() == 0.0
        assert profiler.summary() == "No timings recorded"

    def test_sync_timing(self):
        profiler = JobProfiler()
        with profiler.time("test_step"):
            time.sleep(0.01)
        assert len(profiler._timings) == 1
        assert profiler._timings[0].name == "test_step"
        assert profiler._timings[0].duration_ms > 0

    async def test_async_timing(self):
        profiler = JobProfiler()
        async with profiler.time_async("async_step"):
            pass
        assert len(profiler._timings) == 1
        assert profiler._timings[0].name == "async_step"

    def test_total_ms(self):
        profiler = JobProfiler()
        profiler._timings = [
            TimingResult(name="a", duration_ms=100.0),
            TimingResult(name="b", duration_ms=200.0),
        ]
        assert profiler.total_ms() == 300.0

    def test_summary_format(self):
        profiler = JobProfiler()
        profiler._timings = [
            TimingResult(name="step_a", duration_ms=100.0),
            TimingResult(name="step_b", duration_ms=300.0),
        ]
        summary = profiler.summary()
        assert "Timing breakdown:" in summary
        assert "step_a" in summary
        assert "step_b" in summary
        assert "TOTAL: 400.0ms" in summary
        assert "25.0%" in summary
        assert "75.0%" in summary

    def test_summary_zero_total(self):
        profiler = JobProfiler()
        profiler._timings = [TimingResult(name="zero", duration_ms=0.0)]
        summary = profiler.summary()
        assert "zero" in summary

    async def test_log_summary(self):
        profiler = JobProfiler()
        profiler._timings = [TimingResult(name="x", duration_ms=50.0)]
        logger = MagicMock()
        logger.info = AsyncMock()
        await profiler.log_summary(logger)
        logger.info.assert_called_once()
        assert "x" in logger.info.call_args[0][0]

    async def test_log_summary_empty(self):
        profiler = JobProfiler()
        logger = MagicMock()
        logger.info = AsyncMock()
        await profiler.log_summary(logger)
        logger.info.assert_not_called()

    def test_sync_timing_opens_stage_span(self):
        profiler = JobProfiler()
        with patch("worker.profiler.telemetry.span") as span_cm:
            with profiler.time("alignment"):
                pass
        span_cm.assert_called_once_with("stage.alignment")

    async def test_async_timing_opens_stage_span(self):
        profiler = JobProfiler()
        with patch("worker.profiler.telemetry.span") as span_cm:
            async with profiler.time_async("processing"):
                pass
        span_cm.assert_called_once_with("stage.processing")

    def test_multiple_timings(self):
        profiler = JobProfiler()
        with profiler.time("a"):
            pass
        with profiler.time("b"):
            pass
        with profiler.time("c"):
            pass
        assert len(profiler._timings) == 3
        assert profiler._timings[0].name == "a"
        assert profiler._timings[1].name == "b"
        assert profiler._timings[2].name == "c"
