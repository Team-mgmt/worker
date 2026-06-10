"""Tests for the worker.telemetry module."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

import worker.telemetry as telemetry


@pytest.fixture(autouse=True)
def reset_init_flag(monkeypatch):
    """Reset the module-level _initialized flag between tests."""
    monkeypatch.setattr(telemetry, "_initialized", False)
    yield
    monkeypatch.setattr(telemetry, "_initialized", False)


class TestInitTelemetry:
    def test_no_endpoint_skips_init(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
        assert telemetry.init_telemetry() is False
        assert telemetry._initialized is False

    def test_metrics_only_endpoint_skips_tracer_provider(self, monkeypatch):
        # A metrics-only deployment must NOT stand up a span exporter
        # (OTLPSpanExporter ignores the metrics-specific var and would
        # default to localhost, failing on every export).
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://collector:4318")

        with patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter"), \
             patch("opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader"), \
             patch("opentelemetry.sdk.metrics.MeterProvider"), \
             patch("opentelemetry.metrics.set_meter_provider") as set_provider, \
             patch("opentelemetry.sdk.trace.TracerProvider") as tracer_provider_cls, \
             patch("opentelemetry.trace.set_tracer_provider") as set_tracer_provider:
            assert telemetry.init_telemetry() is True
            set_provider.assert_called_once()
            tracer_provider_cls.assert_not_called()
            set_tracer_provider.assert_not_called()

    def test_traces_only_endpoint_skips_meter_provider(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4318")

        with patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"), \
             patch("opentelemetry.sdk.trace.export.BatchSpanProcessor"), \
             patch("opentelemetry.sdk.trace.TracerProvider"), \
             patch("opentelemetry.trace.set_tracer_provider") as set_tracer_provider, \
             patch("opentelemetry.sdk.metrics.MeterProvider") as meter_provider_cls, \
             patch("opentelemetry.metrics.set_meter_provider") as set_provider:
            assert telemetry.init_telemetry() is True
            set_tracer_provider.assert_called_once()
            meter_provider_cls.assert_not_called()
            set_provider.assert_not_called()

    def test_idempotent_init(self, monkeypatch):
        monkeypatch.setattr(telemetry, "_initialized", True)
        # Should short-circuit even if endpoint is unset.
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert telemetry.init_telemetry() is True

    def test_with_endpoint_initializes_provider(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "30000")

        with patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter") as exporter_cls, \
             patch("opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader") as reader_cls, \
             patch("opentelemetry.sdk.metrics.MeterProvider") as provider_cls, \
             patch("opentelemetry.metrics.set_meter_provider") as set_provider, \
             patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as span_exporter_cls, \
             patch("opentelemetry.sdk.trace.export.BatchSpanProcessor") as span_proc_cls, \
             patch("opentelemetry.sdk.trace.TracerProvider") as tracer_provider_cls, \
             patch("opentelemetry.trace.set_tracer_provider") as set_tracer_provider:
            assert telemetry.init_telemetry(worker_id="abc", hostname="host-1") is True
            exporter_cls.assert_called_once()
            reader_cls.assert_called_once()
            provider_cls.assert_called_once()
            set_provider.assert_called_once_with(provider_cls.return_value)
            span_exporter_cls.assert_called_once()
            span_proc_cls.assert_called_once_with(span_exporter_cls.return_value)
            tracer_provider_cls.assert_called_once()
            tracer_provider_cls.return_value.add_span_processor.assert_called_once_with(
                span_proc_cls.return_value
            )
            set_tracer_provider.assert_called_once_with(tracer_provider_cls.return_value)

        # Reader receives the configured interval.
        _, kwargs = reader_cls.call_args
        assert kwargs["export_interval_millis"] == 30000


class TestRecordHelpers:
    """The helpers should not raise when the SDK is in no-op mode and should
    forward the right attribute keys when the underlying instrument is patched.
    """

    def test_record_scan_no_op_safe(self):
        # Default state: no exporter configured -> no-op meter -> safe.
        telemetry.record_scan(123.0, result="success")
        telemetry.record_scan(50.0, result="failed", error_code="QR_CODE_COUNT_MISMATCH",
                              processor_version=1.0, source="STUDENT")

    def test_record_scan_attributes(self, monkeypatch):
        hist = MagicMock()
        counter = MagicMock()
        monkeypatch.setattr(telemetry, "scan_duration_ms", hist)
        monkeypatch.setattr(telemetry, "scan_count", counter)

        telemetry.record_scan(
            42.0,
            result="failed",
            error_code="QR_NOT_FOUND",
            processor_version=1.0,
            source="TEACHER",
        )
        hist.record.assert_called_once()
        counter.add.assert_called_once()
        attrs = hist.record.call_args[0][1]
        assert attrs == {
            "result": "failed",
            "error_code": "QR_NOT_FOUND",
            "processor_version": "1.0",
            "source": "TEACHER",
        }

    def test_record_step(self, monkeypatch):
        hist = MagicMock()
        monkeypatch.setattr(telemetry, "step_duration_ms", hist)
        telemetry.record_step("binarization", 75.5)
        hist.record.assert_called_once_with(75.5, {"step": "binarization"})

    def test_record_cache_lookup(self, monkeypatch):
        counter = MagicMock()
        monkeypatch.setattr(telemetry, "cache_lookups", counter)
        telemetry.record_cache_lookup("template_thresh", hit=True)
        telemetry.record_cache_lookup("template_thresh", hit=False)
        assert counter.add.call_args_list[0][0][1] == {"cache": "template_thresh", "result": "hit"}
        assert counter.add.call_args_list[1][0][1] == {"cache": "template_thresh", "result": "miss"}

    def test_record_problem_outcome_default_low_cardinality(self, monkeypatch):
        monkeypatch.delenv("METRIC_PER_PROBLEM_LABELS", raising=False)
        counter = MagicMock()
        monkeypatch.setattr(telemetry, "problem_outcomes", counter)
        telemetry.record_problem_outcome(outcome="blank", exam_round_id="round-1", problem_index=3)
        attrs = counter.add.call_args[0][1]
        assert attrs == {"outcome": "blank"}

    def test_record_problem_outcome_with_per_problem_labels(self, monkeypatch):
        monkeypatch.setenv("METRIC_PER_PROBLEM_LABELS", "1")
        counter = MagicMock()
        monkeypatch.setattr(telemetry, "problem_outcomes", counter)
        telemetry.record_problem_outcome(outcome="multi_unexpected", exam_round_id="round-1", problem_index=3)
        attrs = counter.add.call_args[0][1]
        assert attrs == {
            "outcome": "multi_unexpected",
            "exam_round_id": "round-1",
            "problem_index": "3",
        }


class TestSpanHelpers:
    def test_span_no_op_safe(self):
        # Default no-op tracer: opening a span must not raise.
        with telemetry.span("io.file.read", **{"file.path": "/tmp/x"}) as sp:
            assert sp is not None

    def test_span_filters_none_attributes_and_propagates(self, monkeypatch):
        tracer = MagicMock()
        cm = MagicMock()
        span_obj = MagicMock()
        cm.__enter__.return_value = span_obj
        cm.__exit__.return_value = False
        tracer.start_as_current_span.return_value = cm
        monkeypatch.setattr(telemetry, "_tracer", tracer)

        with pytest.raises(ValueError, match="boom"):
            with telemetry.span("cv2.warpPerspective", keep="yes", drop=None):
                raise ValueError("boom")

        # None-valued attributes are dropped before the span starts.
        _, kwargs = tracer.start_as_current_span.call_args
        assert kwargs["attributes"] == {"keep": "yes"}
        # Exception propagates; SDK's start_as_current_span handles
        # record_exception / ERROR status by default.

    def test_start_and_end_current_span_no_op_safe(self):
        sp, token = telemetry.start_current_span("qmr.scan", **{"scan.job_id": "j1"})
        # Ending with attributes (incl. a dropped None) must not raise.
        telemetry.end_current_span(
            sp, token, error=None, **{"scan.result": "success", "scan.error_code": None}
        )

    def test_end_current_span_sets_error_and_attributes(self):
        from opentelemetry import context as otel_context

        # A real token so the internal otel_context.detach() succeeds; the
        # span itself is a mock so we can assert what was set on it.
        token = otel_context.attach(otel_context.get_current())
        span_obj = MagicMock()
        telemetry.end_current_span(
            span_obj,
            token,
            error="kaboom",
            **{"scan.result": "failed", "scan.error_code": None},
        )
        span_obj.set_attribute.assert_called_once_with("scan.result", "failed")
        span_obj.set_status.assert_called_once()
        span_obj.end.assert_called_once()


class TestCv2SpanTracerGating:
    def test_enabled_by_default_when_unset(self, monkeypatch):
        import worker.cv2_span_trace as cst

        monkeypatch.delenv("TRACE_CV2", raising=False)
        with cst.trace_cv2_spans() as tracer:
            assert tracer is not None

    def test_explicit_opt_out_is_no_op(self, monkeypatch):
        import worker.cv2_span_trace as cst

        for falsy in ("0", "false", "no", "off", "FALSE", " 0 "):
            monkeypatch.setenv("TRACE_CV2", falsy)
            with cst.trace_cv2_spans() as tracer:
                assert tracer is None, f"{falsy!r} should opt out"

    def test_enabled_patches_and_restores_cv2(self, monkeypatch):
        import cv2

        import worker.cv2_span_trace as cst

        monkeypatch.delenv("TRACE_CV2", raising=False)
        original = cv2.warpPerspective
        with cst.trace_cv2_spans() as tracer:
            assert tracer is not None
            assert cv2.warpPerspective is not original  # patched
        assert cv2.warpPerspective is original  # restored

    def test_hot_ops_are_not_patched(self, monkeypatch):
        import cv2

        import worker.cv2_span_trace as cst

        monkeypatch.setenv("TRACE_CV2", "1")
        hot_originals = {name: getattr(cv2, name) for name in cst._HOT_OP_SKIPLIST}
        warp_original = cv2.warpPerspective
        with cst.trace_cv2_spans() as tracer:
            # Cheap per-bubble primitives stay the originals (no span wrap).
            for name, orig in hot_originals.items():
                assert getattr(cv2, name) is orig, f"{name} should not be patched"
                assert name not in tracer._originals
            # Structurally interesting ops are still wrapped.
            assert cv2.warpPerspective is not warp_original
        assert cv2.warpPerspective is warp_original  # restored


def test_module_imports_without_sdk_endpoint():
    """The module is safe to import when no exporter is configured."""
    # Importing again should not raise; instruments should exist as no-op shims.
    importlib.reload(telemetry)
    assert telemetry.scan_duration_ms is not None
    assert telemetry.scan_count is not None
    assert telemetry.step_duration_ms is not None
    assert telemetry.cache_lookups is not None
    assert telemetry.problem_outcomes is not None
