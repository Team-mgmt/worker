"""Per-call OTel span tracer for ``cv2``.

Monkey-patches public ``cv2`` callables so each invocation opens a short
``cv2.<name>`` span nested under whatever span is current (a pipeline
stage span). Cheap, extremely-hot primitives (``_HOT_OP_SKIPLIST``) are
deliberately left unpatched — they dominate span volume and overhead
while carrying no diagnostic value. With them excluded, span volume is
O(areas) — dozens per scan — so this is **on by default**. Set
``TRACE_CV2=0`` (or ``false``/``no``/``off``) to opt out. When OTel
export is not configured the spans are non-recording, so the residual
cost is just the (now small) wrapper overhead.

Unlike :mod:`worker.cv2_trace` (debug disk dumps), this records nothing
to disk and adds no encode work — just span open/close around the
original call. When disabled it is a no-op generator yielding ``None``.

The patch is process-global, so this must run single-threaded w.r.t.
cv2 usage; the worker processes one scan at a time, so per-job scope is
safe (same assumption as :mod:`worker.cv2_trace`).
"""

from __future__ import annotations

import functools
import os
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import cv2

from . import telemetry
from .cv2_trace import _is_traceable

_ENV_FLAG = "TRACE_CV2"

# cv2 ops we never span-wrap. Two groups, same effect (span count drops
# from O(bubbles) to O(areas), i.e. dozens/scan instead of thousands):
#
# 1. Cheap, extremely-high-frequency primitives. The per-bubble
#    fill-ratio loop (worker.processors.v1._check_filled_area) calls
#    these ~10-15× per bubble. Each takes only single-digit µs on a
#    bubble ROI, so a ~10 µs span is +200-400% on the call and the
#    dominant source of span volume — yet "cv2.countNonZero" carries
#    almost no diagnostic value.
# 2. Per-bubble image I/O (imwrite/imencode/cvtColor via
#    _save_area_image). These run once per bubble too, and the I/O cost
#    is already captured by the dedicated file/S3 IO spans in
#    worker.worker.scan — a per-call cv2 span here is redundant volume.
#
# What's left gets spans: structurally interesting, per-scan/per-area
# ops (warpPerspective, adaptiveThreshold, findContours, morphologyEx,
# medianBlur, ...).
_HOT_OP_SKIPLIST = frozenset(
    {
        # Group 1: cheap per-bubble measurement primitives.
        "countNonZero",
        "bitwise_and",
        "bitwise_or",
        "bitwise_not",
        "bitwise_xor",
        "mean",
        "meanStdDev",
        "sumElems",
        "minMaxLoc",
        "add",
        "subtract",
        "absdiff",
        "compare",
        "inRange",
        # Group 2: per-bubble image I/O — covered by IO spans instead.
        "imwrite",
        "imencode",
        "cvtColor",
    }
)


def _enabled() -> bool:
    """Enabled by default; explicit falsy value opts out."""
    return os.getenv(_ENV_FLAG, "").strip().lower() not in ("0", "false", "no", "off")


class Cv2SpanTracer:
    """Wraps every traceable ``cv2`` callable in an OTel span."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    def _wrap(self, name: str, fn: Any) -> Callable[..., Any]:
        span_name = f"cv2.{name}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with telemetry.span(span_name):
                return fn(*args, **kwargs)

        return wrapper

    def __enter__(self) -> "Cv2SpanTracer":
        for attr_name in dir(cv2):
            if attr_name in _HOT_OP_SKIPLIST:
                continue
            attr = getattr(cv2, attr_name, None)
            if not _is_traceable(attr_name, attr):
                continue
            try:
                setattr(cv2, attr_name, self._wrap(attr_name, attr))
            except (AttributeError, TypeError):
                continue
            self._originals[attr_name] = attr
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for name, orig in self._originals.items():
            try:
                setattr(cv2, name, orig)
            except (AttributeError, TypeError):
                pass
        self._originals.clear()


@contextmanager
def trace_cv2_spans() -> Iterator[Cv2SpanTracer | None]:
    """Patch cv2 with span wrappers unless ``TRACE_CV2`` opts out."""
    if not _enabled():
        yield None
        return
    tracer = Cv2SpanTracer()
    with tracer:
        yield tracer
