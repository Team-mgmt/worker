"""Process-wide ``cv2`` call tracer for debug runs.

When entered, ``Cv2Tracer`` monkey-patches every public callable on the
``cv2`` module so that each invocation records:

- a sequence number,
- the caller file/line/function and the literal source line text,
- a summary of every positional and keyword argument,
- a summary of the return value,
- elapsed wall-clock time,
- input / output ndarrays dumped to disk (JPEG for 3-channel BGR/RGB
  images, PNG for masks, grayscale, and alpha-bearing images).

The originals are restored on ``__exit__``. The patch is global, so this
must run inside a single-threaded scope w.r.t. cv2 usage; the worker
processes one scan at a time, so per-job tracing is safe.

Encoding runs in a background ``ThreadPoolExecutor`` so the multiple MB
of zlib/libjpeg work per call does not serialize on the producer thread
(cv2 release the GIL during encode → real parallelism). A bounded
semaphore caps in-flight tasks so a fast producer can't pile up hundreds
of full-resolution ndarray copies in RAM.

Cost when ``enabled=False``: a no-op generator yielding ``None``. Cost
when enabled but used outside a process() call: zero (nothing patches
itself until ``__enter__`` runs).
"""

from __future__ import annotations

import json
import linecache
import os
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Iterator

import cv2
import numpy as np

# JPEG quality for 3-channel image dumps. Debug fidelity stays acceptable
# at 90; encode time and on-disk size drop ~5× vs PNG.
_DEFAULT_JPEG_QUALITY = 90

# Encoder pool sizing. Defaults to "leave one core for the main pipeline"
# but cap at 8 so we don't oversubscribe big-instance hosts. PNG/JPEG
# encode releases the GIL inside cv2/libpng/libjpeg, so these are real
# CPU-parallel threads.
_DEFAULT_ENCODE_WORKERS = max(2, min(8, (os.cpu_count() or 4) - 1))

# Names we never wrap. Some are types/classes, some are submodules whose
# attributes we reach via cv2.<sub>.<func> (those won't be patched here —
# acceptable for a first pass; the dominant call site is cv2.foo(...)).
_BLACKLIST = {
    "error",
    "Exception",
    "Mat",
    "MatExpr",
    "UMat",
    "VideoCapture",
    "VideoWriter",
    "FileStorage",
    "ml",
    "dnn",
    "face",
    "aruco",
    "ximgproc",
    "utils",
    "typing",
}


def _is_traceable(name: str, attr: Any) -> bool:
    if name.startswith("_"):
        return False
    if name in _BLACKLIST:
        return False
    if isinstance(attr, type):
        return False
    if not callable(attr):
        return False
    return True


class Cv2Tracer:
    """Records every cv2 call to disk.

    Attributes:
        dump_dir: Directory to write images and the JSON manifest into.
        save_images: When false, only metadata is recorded (no PNGs).
    """

    def __init__(
        self,
        dump_dir: str,
        *,
        save_images: bool = True,
        jpeg_quality: int = _DEFAULT_JPEG_QUALITY,
        encode_workers: int = _DEFAULT_ENCODE_WORKERS,
    ) -> None:
        self.dump_dir = dump_dir
        self.save_images = save_images
        self.jpeg_quality = jpeg_quality
        self.encode_workers = max(1, encode_workers)
        self.records: list[dict] = []
        self._originals: dict[str, Any] = {}
        self._counter = 0
        self._lock = threading.Lock()
        # Captured before patching so internal PNG writes and the
        # non-uint8 viewable-range normalization in _save_array do not
        # re-enter the tracer (which would recurse — _save_array runs
        # while we are still serializing arguments/results for the
        # outer call).
        self._real_imwrite = cv2.imwrite
        self._real_normalize = cv2.normalize
        self._executor: ThreadPoolExecutor | None = None
        # Bounds the in-flight encode queue. Each pending task may hold
        # a freshly-copied ndarray (up to 10s of MB for full-res scans),
        # so without this cap a fast producer would balloon RAM while
        # the encoders catch up. 2× workers is enough slack to keep
        # encoders busy without unbounded growth.
        self._pending: threading.BoundedSemaphore = threading.BoundedSemaphore(self.encode_workers * 2)
        # Dedup map: id(ndarray) → (weakref(ndarray), rel_path). A pure
        # id() cache is unsafe because Python recycles ids after gc, so
        # we pair the id with a weakref and only reuse the cached path
        # when the weakref still resolves to the same object. The map is
        # touched exclusively by the producer thread (the cv2 wrapper),
        # so no extra locking is needed beyond what self._lock already
        # guards. Cleared on __exit__ together with everything else.
        self._dedup: dict[int, tuple[weakref.ref, str]] = {}

    def _summarize(self, value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return {"_": "ndarray", "shape": list(value.shape), "dtype": str(value.dtype)}
        if isinstance(value, (bool, int, float, str)) or value is None:
            return value
        if isinstance(value, (tuple, list)):
            if len(value) > 16:
                return {"_": type(value).__name__, "len": len(value)}
            return [self._summarize(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._summarize(v) for k, v in list(value.items())[:16]}
        return {"_": type(value).__name__, "repr": repr(value)[:200]}

    def _save_array(self, rel_name_stem: str, arr: np.ndarray, *, is_input: bool) -> str | None:
        """Submit an ndarray dump to the encoder pool and return the chosen path.

        Format choice is shape-driven: 3-channel uint8 images (the bulk of
        the bytes — full-res scans, warped views, RGB renders) go to JPEG
        at ``self.jpeg_quality``; everything else (2D masks/grayscale,
        4-channel alpha, non-uint8 normalized views) stays on PNG so
        binary thresholds remain bit-exact.

        ``is_input=True`` snapshots the array before submitting because
        the next cv2 call may mutate it in-place (e.g. dst=src). Outputs
        are fresh buffers and need no copy.

        Dedup: on input observation, if this exact ndarray was already
        written (id+weakref match), the previous path is returned and no
        new encode is queued. Output observations always pop any stale
        cache entry for the result's id (an in-place op may have just
        rewritten that buffer's bytes), then register the fresh path so
        subsequent inputs that reference this output dedup against it.

        Caveat: only detects mutation via cv2's own dst=src style. Pure
        Python ``arr[:] = ...`` between cv2 calls would let a stale path
        slip through. The pipeline doesn't do that, so the trade-off is
        accepted.
        """
        if not self.save_images:
            return None
        if arr.ndim not in (2, 3) or arr.size == 0:
            return None
        if arr.ndim == 3 and arr.shape[2] not in (1, 3, 4):
            return None

        arr_id = id(arr)
        if is_input:
            entry = self._dedup.get(arr_id)
            if entry is not None:
                ref, cached_rel = entry
                if ref() is arr:
                    return cached_rel
                # The weakref died or points elsewhere → id was recycled
                # by Python for a different object. Evict before falling
                # through to a fresh encode for the new occupant.
                self._dedup.pop(arr_id, None)
        else:
            # Output: an existing entry for this id is necessarily stale
            # (the cv2 call we just observed may have rewritten the
            # buffer, or an id-recycle happened). Drop it; we'll
            # re-register with the fresh path below.
            self._dedup.pop(arr_id, None)

        if arr.dtype != np.uint8:
            # Normalize floating / int images to a viewable uint8 range
            # via the pre-patch reference so we don't recurse into our
            # own wrapper while it's serializing args for the outer call.
            try:
                dst = np.empty_like(arr)
                self._real_normalize(arr, dst, 0, 255, cv2.NORM_MINMAX)
                view = dst.astype(np.uint8)
            except cv2.error:
                return None
        else:
            view = arr

        # JPEG only for 3-channel BGR/RGB; masks and alpha-bearing images
        # stay on PNG to preserve exact pixel values.
        if view.ndim == 3 and view.shape[2] == 3:
            ext = ".jpg"
            params: list[int] = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        else:
            ext = ".png"
            params = []

        rel = f"{rel_name_stem}{ext}"
        path = os.path.join(self.dump_dir, rel)

        # Register before encoding so the next producer-thread call can
        # dedup against this path. Encoding is async but ``__exit__``
        # drains all encoders before writing the manifest, so any path
        # referenced from the manifest will resolve on disk.
        try:
            self._dedup[arr_id] = (weakref.ref(arr), rel)
        except TypeError:
            # Some ndarray subclasses (rare — e.g. unusual subclasses
            # without ``__weakref__`` support) can't be weak-referenced.
            # Skip the cache entry rather than crash: we'll just encode
            # this array fresh every time it appears.
            pass

        # Snapshot the payload before handing it to the async encoder.
        # Inputs can be mutated by the next cv2 call (in-place dst=src);
        # outputs can be the SAME buffer cv2 wrote into when called with
        # dst=, or can be mutated by downstream pipeline code before the
        # encoder thread actually reads them. Always copy uint8 views
        # that still alias caller-visible memory; the normalize path
        # already produces an isolated buffer (``dst.astype(uint8)``) so
        # an extra copy there is wasted work. Encoders never see ndarray
        # state newer than this submit point.
        payload = view if view is not arr else view.copy()

        # Backpressure: hold the producer if encoders fall behind so the
        # queue can't accumulate hundreds of full-resolution ndarrays.
        self._pending.acquire()
        executor = self._executor
        if executor is None:
            # Fall back to inline encode (used outside __enter__, mostly
            # for tests and for the wrapping cv2.normalize path).
            try:
                self._encode_to_disk(path, payload, params)
            finally:
                self._pending.release()
            return rel
        executor.submit(self._encode_to_disk_and_release, path, payload, params)
        return rel

    def _encode_to_disk(self, path: str, view: np.ndarray, params: list[int]) -> None:
        """Encode + write a single ndarray. Runs on encoder threads.

        Returns nothing — failure modes are logged here, and the manifest
        is post-processed in ``__exit__`` (``_scrub_missing_paths``) to
        drop references to files that never landed on disk. We can't
        propagate the failure back to ``_save_array`` synchronously
        because that returned before this runs.
        """
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # cv2.imwrite returns False on some failure modes without
            # raising (unwritable target, unsupported codec for the
            # extension, etc.). Log it; the post-exit scrub will drop
            # the dead reference from the manifest.
            if not self._real_imwrite(path, view, params):
                print(f"[Cv2Tracer] imwrite returned False for {path}")
        except Exception as exc:
            # Debug-trace failures must never affect the job; surface as
            # a log line and move on.
            print(f"[Cv2Tracer] encode failed for {path}: {type(exc).__name__}: {exc}")

    def _encode_to_disk_and_release(self, path: str, view: np.ndarray, params: list[int]) -> None:
        try:
            self._encode_to_disk(path, view, params)
        finally:
            self._pending.release()

    def _scrub_missing_paths(self) -> None:
        """Drop manifest references to images that didn't actually land on disk.

        ``_save_array`` registers a rel path optimistically and returns
        before the encoder thread runs, so a silent ``cv2.imwrite``
        failure (returning False) or an exception inside the encoder
        would leave the manifest pointing at a nonexistent file. Run
        this once after the executor drains, before the manifest is
        written, so every path listed in ``cv2_calls.json`` resolves.
        """
        for record in self.records:
            for key in ("input_images", "output_images"):
                paths = record.get(key)
                if not paths:
                    continue
                record[key] = [p for p in paths if os.path.exists(os.path.join(self.dump_dir, p))]

    def _wrap(self, name: str, func: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self._counter += 1
                seq = self._counter
            # sys._getframe(1) is significantly cheaper than inspect.stack();
            # we only need the immediate caller's location.
            frame = sys._getframe(1)
            filename = frame.f_code.co_filename
            lineno = frame.f_lineno
            source = linecache.getline(filename, lineno).strip()
            caller = {
                "file": filename,
                "line": lineno,
                "function": frame.f_code.co_name,
                "source": source,
            }

            input_paths: list[str] = []
            for i, arg in enumerate(args):
                if isinstance(arg, np.ndarray):
                    rel = self._save_array(f"cv2_calls/{seq:05d}_{name}_in_{i}", arg, is_input=True)
                    if rel:
                        input_paths.append(rel)

            t0 = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                with self._lock:
                    self.records.append({
                        "seq": seq,
                        "function": f"cv2.{name}",
                        "caller": caller,
                        "args": [self._summarize(a) for a in args],
                        "kwargs": {str(k): self._summarize(v) for k, v in kwargs.items()},
                        "input_images": input_paths,
                        "raised": {"type": type(exc).__name__, "message": str(exc)},
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
                    })
                raise
            elapsed_ms = (time.perf_counter() - t0) * 1000

            output_paths: list[str] = []
            if isinstance(result, np.ndarray):
                rel = self._save_array(f"cv2_calls/{seq:05d}_{name}_out", result, is_input=False)
                if rel:
                    output_paths.append(rel)
            elif isinstance(result, tuple):
                for i, item in enumerate(result):
                    if isinstance(item, np.ndarray):
                        rel = self._save_array(f"cv2_calls/{seq:05d}_{name}_out_{i}", item, is_input=False)
                        if rel:
                            output_paths.append(rel)

            with self._lock:
                self.records.append({
                    "seq": seq,
                    "function": f"cv2.{name}",
                    "caller": caller,
                    "args": [self._summarize(a) for a in args],
                    "kwargs": {str(k): self._summarize(v) for k, v in kwargs.items()},
                    "result": self._summarize(result),
                    "input_images": input_paths,
                    "output_images": output_paths,
                    "elapsed_ms": round(elapsed_ms, 3),
                })
            return result

        wrapper.__name__ = f"traced_{name}"
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]
        return wrapper

    def __enter__(self) -> "Cv2Tracer":
        os.makedirs(self.dump_dir, exist_ok=True)
        # Stand the encoder pool up before patching so the very first
        # wrapped call already has somewhere to submit.
        self._executor = ThreadPoolExecutor(
            max_workers=self.encode_workers,
            thread_name_prefix="cv2trace-encode",
        )
        for attr_name in dir(cv2):
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
        # Restore cv2 first so any code that runs during executor drain
        # (extremely unlikely, but the shutdown path could in theory log
        # through a cv2 helper one day) doesn't get re-traced.
        for name, orig in self._originals.items():
            try:
                setattr(cv2, name, orig)
            except (AttributeError, TypeError):
                pass
        self._originals.clear()
        # Drain pending encodes before we write the manifest — once the
        # manifest is on disk, every path it references must resolve.
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=True)
        # Dedup map kept weakrefs to job-scoped ndarrays; drop it so a
        # re-entered tracer (unusual but allowed by the API) starts
        # fresh rather than carrying potentially recycled-id ghosts.
        self._dedup.clear()
        # Scrub manifest references to any image whose encode failed
        # silently (cv2.imwrite returning False without raising) so the
        # final JSON only points at files that actually exist on disk.
        self._scrub_missing_paths()
        manifest = os.path.join(self.dump_dir, "cv2_calls.json")
        with open(manifest, "w", encoding="utf-8") as fp:
            json.dump(self.records, fp, ensure_ascii=False, indent=2)


@contextmanager
def trace_cv2(dump_dir: str | None, *, enabled: bool = True, save_images: bool = True) -> Iterator[Cv2Tracer | None]:
    """Context manager that traces cv2 only when ``enabled`` and ``dump_dir`` are set."""
    if not enabled or dump_dir is None:
        yield None
        return
    tracer = Cv2Tracer(dump_dir, save_images=save_images)
    with tracer:
        yield tracer
