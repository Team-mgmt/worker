"""Simple timing profiler for identifying bottlenecks."""

import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

from . import telemetry
from .loggers.database import DatabaseLogger


@dataclass
class TimingResult:
    """Timing result for a single stage."""

    name: str
    duration_ms: float


@dataclass
class JobProfiler:
    """Collects timing data for a single job's processing stages."""

    _timings: list[TimingResult] = field(default_factory=list)

    @contextmanager
    def time(self, name: str):
        """Synchronous context manager to time a named stage.

        Also opens an OTel span ``stage.<name>`` so the timing breakdown
        shows up as a trace, nested under the current span (the per-scan
        root span).
        """
        start = time.perf_counter()
        try:
            with telemetry.span(f"stage.{name}"):
                yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._timings.append(TimingResult(name=name, duration_ms=duration_ms))
            telemetry.record_step(name, duration_ms)

    @asynccontextmanager
    async def time_async(self, name: str):
        """Async context manager to time a named stage.

        Also opens an OTel span ``stage.<name>``; see :meth:`time`.
        """
        start = time.perf_counter()
        try:
            with telemetry.span(f"stage.{name}"):
                yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._timings.append(TimingResult(name=name, duration_ms=duration_ms))
            telemetry.record_step(name, duration_ms)

    def total_ms(self) -> float:
        """Total time across all stages."""
        return sum(t.duration_ms for t in self._timings)

    def summary(self) -> str:
        """Format timing summary as a string."""
        if not self._timings:
            return "No timings recorded"

        total = self.total_ms()
        lines = ["Timing breakdown:"]
        for t in self._timings:
            pct = (t.duration_ms / total * 100) if total > 0 else 0
            lines.append(f"  {t.name}: {t.duration_ms:.1f}ms ({pct:.1f}%)")
        lines.append(f"  TOTAL: {total:.1f}ms")
        return "\n".join(lines)

    async def log_summary(self, logger: DatabaseLogger):
        """Log the timing summary using the provided logger."""
        if self._timings:
            await logger.info(self.summary())
