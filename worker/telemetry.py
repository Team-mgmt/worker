"""OpenTelemetry metrics and traces for the ShelfAlign worker.

Initializes a global ``MeterProvider`` and ``TracerProvider`` that export
via OTLP/HTTP when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set. When the
endpoint is unset, the SDK's default no-op meter/tracer is used, so all
``record_*`` helpers and the ``span()`` context manager below become
cheap no-ops — safe to call from hot paths.

Recorded instruments:

- ``shelfalign.scan.duration`` (histogram, ms): per-scan end-to-end duration
- ``shelfalign.scan.requests`` (counter): per-scan count tagged with result
- ``shelfalign.scan.step.duration`` (histogram, ms): per-step duration tagged with ``step``
- ``shelfalign.scan.cache.lookups`` (counter): cache hits/misses, tagged with ``cache`` and ``result``
- ``shelfalign.scan.problem.outcomes`` (counter): per-problem detection outcomes

``METRIC_PER_PROBLEM_LABELS=1`` opts into high-cardinality
``exam_round_id`` + ``problem_index`` labels on ``problem.outcomes``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)

_initialized = False


def _per_problem_labels_enabled() -> bool:
    return os.getenv("METRIC_PER_PROBLEM_LABELS", "").lower() in ("1", "true", "yes")


def init_telemetry(*, worker_id: str | None = None, hostname: str | None = None) -> bool:
    """Configure the global meter and tracer providers with OTLP/HTTP exporters.

    Metrics and traces are gated independently on their own endpoints so a
    metrics-only deployment doesn't stand up a span exporter that would
    default to localhost and fail on every export. Returns ``True`` when at
    least one signal was wired up; otherwise the SDK is left untouched and
    all instruments and spans fall back to no-ops.
    """
    global _initialized
    if _initialized:
        return True

    # OTLPMetricExporter reads OTEL_EXPORTER_OTLP_(METRICS_)ENDPOINT;
    # OTLPSpanExporter reads OTEL_EXPORTER_OTLP_(TRACES_)ENDPOINT. The
    # signal-specific vars are not interchangeable, so trigger each
    # provider only on an endpoint its exporter can actually use.
    base_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    metrics_endpoint = base_endpoint or os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    traces_endpoint = base_endpoint or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not metrics_endpoint and not traces_endpoint:
        logger.info("No OTLP endpoint set; metrics and traces export disabled")
        return False

    # Defer SDK imports so dev environments that don't install the
    # exporter wheel still import this module cleanly.
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    attrs: dict[str, Any] = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "shelfalign-worker"),
    }
    if worker_id:
        attrs["service.instance.id"] = worker_id
        attrs["worker.id"] = worker_id
    if hostname:
        attrs["host.name"] = hostname
    resource = Resource.create(attrs)

    if metrics_endpoint:
        raw_interval = os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "60000")
        try:
            interval_ms = int(raw_interval)
            if interval_ms <= 0:
                raise ValueError("interval must be positive")
        except ValueError:
            logger.warning(
                "Invalid OTEL_METRIC_EXPORT_INTERVAL_MS=%r; falling back to 60000ms",
                raw_interval,
            )
            interval_ms = 60000
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(),
            export_interval_millis=interval_ms,
        )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    if traces_endpoint:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)

    _initialized = True
    logger.info(
        "OTel exporters configured (metrics=%s, traces=%s)",
        "on" if metrics_endpoint else "off",
        "on" if traces_endpoint else "off",
    )
    return True


_tracer = trace.get_tracer("shelfalign.worker", "1.0")


def get_tracer() -> trace.Tracer:
    """Return the worker tracer.

    Resolves to the real tracer once :func:`init_telemetry` has set a
    provider; otherwise the SDK's no-op tracer (zero-cost spans).
    """
    return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Open a span as the current span, recording exceptions and status.

    A cheap no-op when no tracer provider is configured. ``attributes``
    are attached at start; ``None`` values are dropped so callers can
    pass optional context unconditionally. ``start_as_current_span``
    records the exception and sets an ERROR status on escape by default.
    """
    clean = {k: v for k, v in attributes.items() if v is not None}
    with _tracer.start_as_current_span(name, attributes=clean) as current:
        yield current


def start_current_span(name: str, **attributes: Any) -> tuple[trace.Span, object]:
    """Start a span and attach it as the current span out-of-line.

    Returns ``(span, token)``. The caller MUST pass both to
    :func:`end_current_span` to detach the context and end the span.
    Use this only where a ``with`` block can't wrap the scope (e.g. a
    long try/except/finally that would otherwise need re-indenting);
    prefer :func:`span` everywhere else.
    """
    from opentelemetry import context as otel_context

    clean = {k: v for k, v in attributes.items() if v is not None}
    current = _tracer.start_span(name, attributes=clean)
    token = otel_context.attach(trace.set_span_in_context(current))
    return current, token


def end_current_span(
    current: trace.Span,
    token: object,
    *,
    error: str | None = None,
    **attributes: Any,
) -> None:
    """Detach and end a span opened by :func:`start_current_span`.

    Sets an ERROR status when ``error`` is given. Extra ``attributes``
    (non-``None``) are recorded before the span ends.
    """
    from opentelemetry import context as otel_context

    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(key, value)
    if error:
        current.set_status(trace.Status(trace.StatusCode.ERROR, error))
    otel_context.detach(token)  # type: ignore[arg-type]
    current.end()


_meter = metrics.get_meter("shelfalign.worker", "1.0")

scan_duration_ms = _meter.create_histogram(
    name="shelfalign.scan.duration",
    unit="ms",
    description="End-to-end processing duration of a scan job",
)
scan_count = _meter.create_counter(
    name="shelfalign.scan.requests",
    description="Total scan jobs processed",
)
step_duration_ms = _meter.create_histogram(
    name="shelfalign.scan.step.duration",
    unit="ms",
    description="Per-step processing duration inside a scan",
)
cache_lookups = _meter.create_counter(
    name="shelfalign.scan.cache.lookups",
    description="Disk cache lookups, partitioned by hit/miss",
)
problem_outcomes = _meter.create_counter(
    name="shelfalign.scan.problem.outcomes",
    description="Per-problem detection outcomes (blank/single/multi)",
)


def record_scan(
    duration_ms: float,
    *,
    result: str,
    error_code: str | None = None,
    processor_version: float | None = None,
    source: str | None = None,
) -> None:
    """Record a completed scan's duration and result.

    ``result`` is the high-level outcome ("success" / "failed"). ``error_code``
    captures the structured failure code on the failure paths so error rate
    can be sliced per code.
    """
    attrs: dict[str, Any] = {"result": result}
    if error_code:
        attrs["error_code"] = error_code
    if processor_version is not None:
        attrs["processor_version"] = str(processor_version)
    if source:
        attrs["source"] = source
    scan_duration_ms.record(duration_ms, attrs)
    scan_count.add(1, attrs)


def record_step(name: str, duration_ms: float) -> None:
    """Record a per-step latency observation."""
    step_duration_ms.record(duration_ms, {"step": name})


def record_cache_lookup(cache: str, *, hit: bool) -> None:
    """Record a cache hit or miss."""
    cache_lookups.add(1, {"cache": cache, "result": "hit" if hit else "miss"})


def record_problem_outcome(
    *,
    outcome: str,
    exam_round_id: str | None = None,
    problem_index: int | None = None,
) -> None:
    """Record a per-problem detection outcome.

    ``exam_round_id`` and ``problem_index`` are only attached when
    ``METRIC_PER_PROBLEM_LABELS`` is enabled, to keep cardinality
    bounded by default.
    """
    attrs: dict[str, Any] = {"outcome": outcome}
    if _per_problem_labels_enabled():
        if exam_round_id is not None:
            attrs["exam_round_id"] = exam_round_id
        if problem_index is not None:
            attrs["problem_index"] = str(problem_index)
    problem_outcomes.add(1, attrs)
