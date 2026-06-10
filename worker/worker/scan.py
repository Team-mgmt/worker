from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Coroutine, cast

import aiofiles
import uuid7
from sqlalchemy import CursorResult, delete, exists, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client
from sqlalchemy.orm import selectinload

from ..api_client import get_api_client
from ..consts import (
    EXAM_NAME_AREA_TYPE,
    JOB_MAX_RETRIES,
    JOB_TIMEOUT_MINUTES,
    NAME_HISTORY_SOURCE_WORKER,
    NIL_UUID,
)
from ..debug_sync import DebugSyncWorker
from ..generated.models import (
    DraftSubmission,
    DraftSubmissionAnswer,
    Exam,
    ExamPaperArea,
    ExamPaperAreaType,
    ExamProblem,
    ExamProblemSet,
    ExamSubmission,
    ExamSubmissionAnswer,
    ScanRequest,
    ScanRequestJob,
)
from ..loggers.database import DatabaseLogger
from ..cache import SVG_PNG_SUBDIR, TEMPLATE_THRESH_SUBDIR
from ..paths import CACHE_DIR, IMAGES_DIR, get_request_results_dir, get_results_dir
from ..processors import BaseProcessor, get_processor
from ..profiler import JobProfiler
from .. import telemetry
from ..types import UUID, ProcessError, ProcessResult
from ..util import is_valid_student_id, prepare_image
from .disk import DiskMonitorWorker


def _iso8601_utc_now() -> str:
    """Current UTC time as an ISO-8601 string, millisecond precision, 'Z' suffix.

    Independent of the naive ``datetime.now()`` used for DB columns elsewhere in
    this module — this value is embedded in submission.metadata JSON and must be
    an explicit UTC instant (e.g. ``2026-05-16T12:34:56.789Z``).
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ScanWorker:
    def __init__(self, client: S3Client, bucket_name: str, engine: AsyncEngine, worker_id: UUID):
        self.client = client
        self.bucket_name = bucket_name
        self.engine = engine
        self.worker_id = worker_id
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._last_activity_time: float = time.time()
        self._activity_lock = asyncio.Lock()
        self._disk_monitor = DiskMonitorWorker(
            cache_dirs=[
                os.path.join(CACHE_DIR, TEMPLATE_THRESH_SUBDIR),
                os.path.join(CACHE_DIR, SVG_PNG_SUBDIR),
            ]
        )
        self._debug_sync = DebugSyncWorker()
        self._shutdown_requested = False
        self._ready = False

    def request_shutdown(self):
        """Request graceful shutdown. The worker will finish the current job and exit."""
        print("[Worker] Shutdown requested, finishing current job...")
        self._shutdown_requested = True

    async def _derive_student_id(
        self,
        student_info_results: dict[int, list[str]],
        identifier_areas: list[ExamPaperArea],
        logger: DatabaseLogger | None = None,
    ) -> str:
        """Derive student ID from student info detection results via backend API.

        Calls the backend API to stringify choice localIds for each IDENTIFIER area.

        Args:
            student_info_results: dict[area.index, list[detected_localIds]]
            identifier_areas: List of IDENTIFIER ExamPaperAreas with area_type loaded
            logger: Optional DatabaseLogger for emitting per-area diagnostic logs.

        Returns:
            Stringified student ID from concatenated API responses
        """
        if not student_info_results:
            return ""

        api_client = get_api_client()
        if api_client is None:
            # Fallback to simple concatenation if API client not available
            if logger is not None:
                await logger.warn("_derive_student_id: api_client is None, using local fallback")
            return self._derive_student_id_fallback(student_info_results)

        # Build area.index -> area mapping
        area_by_index = {a.index: a for a in identifier_areas}

        sorted_indices = sorted(student_info_results.keys())
        parts = []
        for idx in sorted_indices:
            detected = student_info_results[idx]
            area = area_by_index.get(idx)

            if not detected or area is None:
                parts.append("_")
                continue

            # Get choice_type_id from area's area_type
            choice_type_id = area.area_type.choice_type_id if area.area_type else None
            if choice_type_id is None:
                # No choice_type configured, use fallback
                fallback = detected[0] if len(detected) == 1 else "*"
                if logger is not None:
                    await logger.warn(
                        f"_derive_student_id: area.index={idx} has no choice_type_id "
                        f"(area_type={area.area_type.id if area.area_type else None}), "
                        f"localIds={detected} -> fallback={fallback!r}"
                    )
                parts.append(fallback)
                continue

            # Call API to stringify the localIds
            stringified = await api_client.stringify_choices(choice_type_id, detected)
            if stringified is not None:
                if logger is not None:
                    await logger.info(f"_derive_student_id: area.index={idx} choiceTypeId={choice_type_id} localIds={detected} -> stringified={stringified!r}")
                parts.append(stringified)
            else:
                # API call failed, use fallback
                fallback = detected[0] if len(detected) == 1 else "*"
                if logger is not None:
                    await logger.warn(
                        f"_derive_student_id: area.index={idx} choiceTypeId={choice_type_id} "
                        f"localIds={detected} -> stringify_choices returned None "
                        f"(check stdout for HTTP status / response body), fallback={fallback!r}"
                    )
                parts.append(fallback)

        return "".join(parts)

    def _is_exam_name_unresolved(
        self,
        metadata_areas: list[ExamPaperArea],
        metadata_payload: dict[str, Any],
    ) -> bool:
        """True iff an EXAM_NAME metadata area exists but no resolved name was
        injected into the payload.

        ``_derive_metadata_payload`` only writes the ``nameHistory`` key when an
        EXAM_NAME area stringifies to a non-empty value, so its absence (given an
        EXAM_NAME area is present) means the name could not be resolved.
        """
        has_exam_name_area = any(a.area_type is not None and a.area_type.display_name == EXAM_NAME_AREA_TYPE for a in metadata_areas)
        return has_exam_name_area and "nameHistory" not in metadata_payload

    def _force_draft_for_unresolved_name(
        self,
        exam_name_unresolved: bool,
        scan_request_source: str,
    ) -> bool:
        """Force a DraftSubmission when the exam name is unresolved — except for
        TEACHER scans, which always go to a direct ExamSubmission."""
        return exam_name_unresolved and scan_request_source != "TEACHER"

    async def _derive_metadata_payload(
        self,
        metadata_results: dict[UUID, list[str]],
        metadata_areas: list[ExamPaperArea],
        logger: DatabaseLogger | None = None,
    ) -> dict[str, Any]:
        """Stringify METADATA detections into the submission.metadata JSON payload.

        Each METADATA area has its own choice_type; we run that type's from_choices
        via the backend API (matching IDENTIFIER stringification) and key the result
        by ExamPaperArea.id (stringified) so the frontend can match each value back
        to the originating area.

        Areas whose stringification fails are skipped rather than failing the whole
        scan — METADATA is auxiliary teacher-supplied data, not exam answers.
        """
        if not metadata_results:
            return {}

        area_by_id = {a.id: a for a in metadata_areas}
        api_client = get_api_client()
        payload: dict[str, Any] = {}

        for area_id, local_ids in metadata_results.items():
            area = area_by_id.get(area_id)
            if area is None or area.area_type is None:
                if logger is not None:
                    await logger.warn(f"_derive_metadata_payload: area_id={area_id} not found in metadata_areas or has no area_type, skipping")
                continue

            choice_type_id = area.area_type.choice_type_id
            if choice_type_id is None:
                if logger is not None:
                    await logger.warn(f"_derive_metadata_payload: area_id={area_id} has no choice_type_id, skipping")
                continue

            if api_client is None:
                if logger is not None:
                    await logger.warn(f"_derive_metadata_payload: api_client is None, skipping area_id={area_id}")
                continue

            try:
                stringified = await api_client.stringify_choices(choice_type_id, local_ids)
            except Exception as exc:  # noqa: BLE001 — log + skip per-area, don't fail the scan
                if logger is not None:
                    await logger.warn(f"_derive_metadata_payload: area_id={area_id} choiceTypeId={choice_type_id} raised {type(exc).__name__}: {exc}, skipping")
                continue

            if stringified is None:
                if logger is not None:
                    await logger.warn(
                        f"_derive_metadata_payload: area_id={area_id} choiceTypeId={choice_type_id} localIds={local_ids} -> stringify_choices returned None, skipping"
                    )
                continue

            payload[str(area_id)] = stringified
            if logger is not None:
                await logger.info(f"_derive_metadata_payload: area_id={area_id} choiceTypeId={choice_type_id} localIds={local_ids} -> stringified={stringified!r}")

            # An EXAM_NAME area's resolved value seeds the submission's editable
            # name + its history. First EXAM_NAME area with a non-empty value
            # wins; an empty value leaves the name unresolved (forces a draft
            # downstream for non-teacher scans).
            if area.area_type.display_name == EXAM_NAME_AREA_TYPE and stringified and "nameHistory" not in payload:
                payload["currentNameEditId"] = NIL_UUID
                payload["nameHistory"] = [
                    {
                        "id": NIL_UUID,
                        "name": stringified,
                        "editedAt": _iso8601_utc_now(),
                        "source": NAME_HISTORY_SOURCE_WORKER,
                    }
                ]
                if logger is not None:
                    await logger.info(f"_derive_metadata_payload: EXAM_NAME area_id={area_id} -> seeded nameHistory name={stringified!r}")

        return payload

    def _derive_student_id_fallback(self, student_info_results: dict[int, list[str]]) -> str:
        """Fallback student ID derivation when API is not available.

        Encoding per position:
        - '_' for blank (no detection)
        - The localId value for single detection
        - '*' for multiple detections
        """
        if not student_info_results:
            return ""

        sorted_indices = sorted(student_info_results.keys())
        parts = []
        for idx in sorted_indices:
            detected = student_info_results[idx]
            if len(detected) == 0:
                parts.append("_")
            elif len(detected) == 1:
                parts.append(detected[0])
            else:
                parts.append("*")
        return "".join(parts)

    def _is_valid_scan_result(
        self,
        student_id: str,
        problem_results: dict[UUID, list[str]],
        problem_map: dict[UUID, ExamProblem],
        multi_select_by_area_id: dict[UUID, bool],
    ) -> bool:
        """Whether the scan result is unambiguous enough to skip the draft phase.

        A scan result is valid when:
        1. studentId is resolved successfully (no blanks or multi-selections).
        2. Every problem has at least one detected answer.
        3. Only multi-select problems have more than one detected answer.
        """
        if not is_valid_student_id(student_id):
            return False
        for problem_id, problem in problem_map.items():
            answers = problem_results.get(problem_id) or []
            if len(answers) == 0:
                return False
            if len(answers) > 1 and not multi_select_by_area_id.get(problem.exam_paper_area_id, False):
                return False
        return True

    def _calculate_score(self, problem_results: dict[UUID, list[str]], problem_map: dict[UUID, ExamProblem]) -> float:
        """Calculate total score by comparing detected localIds with correct answers.

        Args:
            problem_results: dict[problem_id, list[detected_localIds]]
            problem_map: dict[problem_id, ExamProblem]

        Returns:
            Total score (sum of scores for correctly answered problems)
        """
        total_score = 0.0

        for problem_id, detected_local_ids in problem_results.items():
            problem = problem_map.get(problem_id)
            if problem is None or problem.answer is None:
                continue

            # Both are now list[str] (localIds) - direct comparison
            if sorted(detected_local_ids) == sorted(problem.answer):
                total_score += problem.score

        return total_score

    async def update_activity(self):
        async with self._activity_lock:
            self._last_activity_time = time.time()

    async def get_last_activity_time(self) -> float:
        async with self._activity_lock:
            return self._last_activity_time

    def set_ready(self, ready: bool = True) -> None:
        self._ready = ready

    def is_ready(self) -> bool:
        return self._ready

    def _create_logger(self, job_id: UUID, scan_request_id: UUID) -> DatabaseLogger:
        return DatabaseLogger(self.session_factory, job_id, scan_request_id, self.worker_id)

    async def _send_heartbeat(self, job_id: UUID):
        async with self.session_factory() as session:
            await session.execute(update(ScanRequestJob).where(ScanRequestJob.id == job_id).values(heartbeat_at=datetime.now()))
            await session.commit()

    def _create_processor(self, version: float) -> BaseProcessor:
        """Create a processor for the given version."""
        processor_class = get_processor(version)
        return processor_class(self.client, self.bucket_name, self.engine)

    def _cleanup_processed_images(self, request_id: UUID, job_id: UUID, image_key: str):
        """Clean up processed images after job completion (but not background/template images)."""
        # Clean up results directory
        results_dir = get_results_dir(request_id, job_id)
        if os.path.exists(results_dir):
            shutil.rmtree(results_dir)
            print(f"[Cleanup][{job_id}] Removed results directory: {results_dir}")

        # Clean up input scan image
        extension = pathlib.Path(image_key).suffix
        input_image_path = os.path.join(IMAGES_DIR, f"{request_id}{extension}")
        if os.path.exists(input_image_path):
            os.remove(input_image_path)
            print(f"[Cleanup][{job_id}] Removed input image: {input_image_path}")

        # Clean up empty parent directories
        request_results_dir = get_request_results_dir(request_id)
        if os.path.exists(request_results_dir) and not os.listdir(request_results_dir):
            os.rmdir(request_results_dir)

    async def upload_results(self, job_id: UUID, request_id: UUID, result: ProcessResult, original_key: str):
        organization_id = result["organization_id"]
        annotations = result["annotations"]
        annotations_cropped = result["annotations_cropped"]
        base_key = f"{organization_id}/scans/{request_id}/{job_id}"

        # Convert numpy arrays to lists for JSON serialization
        annotations_serializable = [{"data": ann["data"].tolist(), "type": ann["type"], "value": ann["value"]} for ann in annotations]
        annotations_cropped_serializable = [{"data": ann["data"].tolist(), "type": ann["type"], "value": ann["value"]} for ann in annotations_cropped]

        # Prepare JSON payloads
        area_metrics_json = json.dumps(result["area_metrics"], ensure_ascii=False).encode("utf-8")
        annotations_json = json.dumps(annotations_serializable, ensure_ascii=False).encode("utf-8")
        annotations_cropped_json = json.dumps(annotations_cropped_serializable, ensure_ascii=False).encode("utf-8")
        results_json = json.dumps(
            {"params": result["processing_params"].model_dump(), "meta": result["processing_meta"]},
            ensure_ascii=False,
        ).encode("utf-8")

        # Read all image files in parallel
        async def read_file(path: str) -> bytes:
            with telemetry.span("io.file.read", **{"file.path": path}) as file_span:
                async with aiofiles.open(path, "rb") as f:
                    data = await f.read()
                file_span.set_attribute("file.size_bytes", len(data))
                return data

        file_read_tasks = [
            read_file(result["image_annotated_cropped_path"]),
            read_file(result["image_flattened_path"]),
            read_file(result["image_threshold_path"]),
        ]
        # Read area images
        area_items = list(result["area_image_paths"].items())
        for _, area_path in area_items:
            file_read_tasks.append(read_file(area_path))

        with telemetry.span("io.file.read_all", **{"file.count": len(file_read_tasks)}):
            file_contents = await asyncio.gather(*file_read_tasks)
        annotated_cropped_data = file_contents[0]
        flattened_data = file_contents[1]
        threshold_data = file_contents[2]
        area_data_list = file_contents[3:]

        # Build all upload tasks
        upload_tasks: list[Coroutine[Any, Any, Any]] = []

        # Copy original scan image using S3 copy (faster than download + upload)
        original_extension = pathlib.Path(original_key).suffix
        upload_tasks.append(
            self.client.copy_object(
                Bucket=self.bucket_name,
                CopySource={"Bucket": self.bucket_name, "Key": original_key},
                Key=f"{base_key}/original{original_extension}",
            )
        )

        # Image uploads
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/annotated_cropped.png",
                Body=annotated_cropped_data,
                ContentType="image/png",
            )
        )
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/flattened.png",
                Body=flattened_data,
                ContentType="image/png",
            )
        )
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/threshold.png",
                Body=threshold_data,
                ContentType="image/png",
            )
        )

        # Area image uploads
        for (area_key, _), area_data in zip(area_items, area_data_list):
            upload_tasks.append(
                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=f"{base_key}/areas/{area_key}.png",
                    Body=area_data,
                    ContentType="image/png",
                )
            )

        # JSON uploads
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/area_metrics.json",
                Body=area_metrics_json,
                ContentType="application/json",
            )
        )
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/annotations.json",
                Body=annotations_json,
                ContentType="application/json",
            )
        )
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/annotations_cropped.json",
                Body=annotations_cropped_json,
                ContentType="application/json",
            )
        )
        upload_tasks.append(
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"{base_key}/results.json",
                Body=results_json,
                ContentType="application/json",
            )
        )

        # Execute all uploads in parallel
        with telemetry.span("io.s3.upload_all", **{"s3.object_count": len(upload_tasks)}):
            await asyncio.gather(*upload_tasks)

    async def start(self) -> None:
        await self._debug_sync.start()
        try:
            await self._run_loop()
        finally:
            # Stop the debug sync regardless of how the polling loop exited
            # — graceful shutdown, uncaught DB error in stale-job cleanup,
            # session-factory failure, etc. — so the background sync task
            # never outlives the worker.
            await self._debug_sync.stop()
        print("[Worker] Graceful shutdown completed")

    async def _run_loop(self) -> None:
        async with self.session_factory() as session:
            while not self._shutdown_requested:
                await self.update_activity()
                # Check disk usage and cleanup templates if needed
                self._disk_monitor.check_and_cleanup()
                # Mark stale jobs as failed and reset their ScanRequests
                stale_job_subquery = select(ScanRequestJob.id).where(
                    ScanRequestJob.finished_at.is_(None),
                    ScanRequestJob.heartbeat_at < text(f"NOW() - INTERVAL '{JOB_TIMEOUT_MINUTES} minutes'"),
                )
                await session.execute(update(ScanRequestJob).where(ScanRequestJob.id.in_(stale_job_subquery)).values(finished_at=datetime.now(), result="FAILED"))

                stale_job_exists = exists(
                    select(ScanRequestJob.id).where(
                        ScanRequestJob.scan_request_id == ScanRequest.id,
                        ScanRequestJob.finished_at.is_(None),
                        ScanRequestJob.heartbeat_at < text(f"NOW() - INTERVAL '{JOB_TIMEOUT_MINUTES} minutes'"),
                    )
                )
                await session.execute(
                    update(ScanRequest)
                    .where(
                        ScanRequest.success_at.is_(None),
                        ScanRequest.deleted_at.is_(None),
                        ScanRequest.failed_at.is_(None),
                        ScanRequest.picked_at.is_not(None),
                        stale_job_exists,
                    )
                    .values(picked_at=None)
                )
                await session.commit()

                # Atomic pick using UPDATE with subquery and RETURNING
                subquery = (
                    select(ScanRequest.id)
                    .where(
                        ScanRequest.success_at.is_(None),
                        ScanRequest.deleted_at.is_(None),
                        ScanRequest.failed_at.is_(None),
                        ScanRequest.picked_at.is_(None),
                        ScanRequest.picked_times < JOB_MAX_RETRIES,
                    )
                    .order_by(ScanRequest.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                    .scalar_subquery()
                )

                now = datetime.now()
                result = await session.execute(
                    update(ScanRequest)
                    .where(ScanRequest.id == subquery)
                    .values(picked_at=now, picked_times=ScanRequest.picked_times + 1, last_picked_at=now)
                    .returning(ScanRequest)
                )
                scan_request = result.scalar_one_or_none()

                if scan_request is None:
                    await session.commit()
                    await asyncio.sleep(5)
                    continue

                job_result = await session.execute(
                    insert(ScanRequestJob).values(id=uuid7.create(), scan_request_id=scan_request.id, worker_id=self.worker_id).returning(ScanRequestJob)
                )
                job = job_result.scalar_one()

                # Extract values before commit to avoid DetachedInstanceError
                scan_request_id = scan_request.id
                scan_request_key = scan_request.key
                scan_request_metadata = scan_request.metadata_
                scan_request_source = scan_request.source
                job_id = job.id

                await session.commit()

                logger = self._create_logger(job_id, scan_request_id)
                profiler = JobProfiler()

                # Track organization_id as early as possible for error reporting
                organization_id: UUID | None = None

                # Per-scan telemetry: tracked across all exit paths so the
                # scan_duration histogram and scan_count counter stay aligned.
                scan_start = time.perf_counter()
                scan_result: str = "failed"
                scan_error_code: str | None = None
                processor_version: float | None = None

                # Root span for the whole scan; profiler stage spans and
                # matcher/cv2/IO spans nest under it via context.
                scan_span, scan_span_token = telemetry.start_current_span(
                    "qmr.scan",
                    **{
                        "scan.job_id": str(job_id),
                        "scan.request_id": str(scan_request_id),
                        "scan.source": scan_request_source,
                    },
                )

                try:
                    # Load image
                    async with profiler.time_async("image_download"):
                        # Scans are always raster (PNG/JPG) — the SVG branch
                        # never fires for scan requests, so we omit
                        # ``svg_min_render_width`` and discard the source
                        # scale (always 1.0 here).
                        image, _ = await prepare_image(self.client, self.bucket_name, scan_request_id, scan_request_key, "images")
                    await self._send_heartbeat(job_id)

                    # Get processor version from metadata, default to 1.0
                    version = scan_request_metadata.get("processor_version", 1.0)
                    processor_version = version
                    await logger.info(f"Using processor version: {version}")
                    await self._send_heartbeat(job_id)

                    # Create version-specific processor and process
                    processor = self._create_processor(version)
                    processor.set_logger(logger)
                    processor.set_profiler(profiler)
                    async with profiler.time_async("processing"):
                        process_result = await processor.process(image, job_id, scan_request_id, scan_request_metadata)
                    await self._send_heartbeat(job_id)

                    # Update organization_id as early as possible
                    organization_id = process_result["organization_id"]
                    await session.execute(update(ScanRequestJob).where(ScanRequestJob.id == job_id).values(organization_id=organization_id))
                    await session.commit()

                    # Upload results
                    async with profiler.time_async("results_upload"):
                        await self.upload_results(job_id, scan_request_id, process_result, scan_request_key)
                    await self._send_heartbeat(job_id)

                    # Fetch exam problems for scoring
                    async with profiler.time_async("scoring_and_submission"):
                        now = datetime.now()
                        exam_id = process_result["exam_id"]
                        exam_round_id = process_result["exam_round_id"]

                        # Step 1: Load exam and check for condition
                        exam_result = await session.execute(select(Exam).where(Exam.id == exam_id))
                        exam = exam_result.scalar_one()

                        # Load IDENTIFIER areas with area_type (and choice_type) for student ID stringification
                        # and multi-select classification.
                        identifier_areas_result = await session.execute(
                            select(ExamPaperArea)
                            .where(ExamPaperArea.exam_paper_id == exam.exam_paper_id)
                            .options(selectinload(ExamPaperArea.area_type).selectinload(ExamPaperAreaType.choice_type))
                        )
                        all_areas = list(identifier_areas_result.scalars().all())
                        multi_select_by_area_id: dict[UUID, bool] = {
                            a.id: bool(a.area_type.choice_type.multi_select) for a in all_areas if a.area_type is not None and a.area_type.choice_type is not None
                        }
                        identifier_areas = [a for a in all_areas if a.area_type and a.area_type.base_type == "IDENTIFIER"]
                        metadata_areas = [a for a in all_areas if a.area_type and a.area_type.base_type == "METADATA"]

                        # Step 2: Determine which problem set to use
                        problem_set_id: UUID | None = None

                        # Get all problem sets for this exam
                        problem_sets_result = await session.execute(select(ExamProblemSet).where(ExamProblemSet.exam_id == exam_id))
                        problem_sets = list(problem_sets_result.scalars().all())

                        # Build area_id -> detected value mapping (separate maps by area type to avoid index collisions)
                        identifier_areas_by_idx = {a.index: a.id for a in all_areas if a.area_type and a.area_type.base_type == "IDENTIFIER"}
                        problem_areas_by_idx = {a.index: a.id for a in all_areas if a.area_type and a.area_type.base_type == "PROBLEM"}
                        option_areas_by_idx = {a.index: a.id for a in all_areas if a.area_type and a.area_type.base_type == "OPTION"}

                        detected_by_area_id: dict[UUID, str] = {}
                        for idx, local_ids in process_result["student_info_results"].items():
                            if idx in identifier_areas_by_idx and local_ids:
                                detected_by_area_id[identifier_areas_by_idx[idx]] = local_ids[0]  # Use first detected value
                        for idx, local_ids in process_result["problem_results"].items():
                            if idx in problem_areas_by_idx and local_ids:
                                detected_by_area_id[problem_areas_by_idx[idx]] = local_ids[0]
                        for idx, local_ids in process_result["option_results"].items():
                            if idx in option_areas_by_idx and local_ids:
                                detected_by_area_id[option_areas_by_idx[idx]] = local_ids[0]

                        # Find matching problem set by area_id and area_value
                        default_set: ExamProblemSet | None = None
                        for ps in problem_sets:
                            if ps.default:
                                # This is the default set
                                default_set = ps
                            if ps.area_id in detected_by_area_id:
                                assert ps.area_id is not None
                                if ps.area_value == detected_by_area_id[ps.area_id]:
                                    problem_set_id = ps.id
                                    await logger.info(f"Matched problem set by area condition: {problem_set_id}")
                                    break

                        # Step 3: Fallback to default if no match found
                        if problem_set_id is None:
                            if default_set is None:
                                # Check if problem sets require OPTION detection that wasn't found
                                required_area_ids = {ps.area_id for ps in problem_sets if ps.area_id is not None}
                                missing_area_ids = required_area_ids - set(detected_by_area_id.keys())
                                if missing_area_ids:
                                    # Find the OPTION areas that weren't detected
                                    option_areas = [a for a in all_areas if a.area_type and a.area_type.base_type == "OPTION"]
                                    missing_option_areas = [a for a in option_areas if a.id in missing_area_ids]
                                    if missing_option_areas:
                                        area_names = [a.area_type.name if a.area_type else str(a.id) for a in missing_option_areas]
                                        raise ProcessError(
                                            f"Option marking not detected. Please check that the exam type is clearly marked. Missing: {', '.join(area_names)}",
                                            code="OPTION_NOT_DETECTED",
                                            params={"missing_areas": area_names},
                                        )
                                raise ProcessError(
                                    "No default problem set found for exam",
                                    code="NO_DEFAULT_PROBLEM_SET",
                                )
                            problem_set_id = default_set.id
                            await logger.info(f"Using default problem set: {problem_set_id}")

                        # Step 4: Query problems for the selected problem set
                        exam_problems_result = await session.execute(
                            select(ExamProblem).where(ExamProblem.exam_problem_set_id == problem_set_id).options(selectinload(ExamProblem.exam_paper_area))
                        )
                        exam_problems = list(exam_problems_result.scalars().all())

                        # Map by area.index instead of problem_number
                        area_index_to_problem: dict[int, ExamProblem] = {p.exam_paper_area.index: p for p in exam_problems}
                        problem_map: dict[UUID, ExamProblem] = {p.id: p for p in exam_problems}

                        # Convert process results (keyed by area.index, values are localIds)
                        problem_results: dict[UUID, list[str]] = {
                            area_index_to_problem[area_index].id: local_ids
                            for area_index, local_ids in process_result["problem_results"].items()
                            if area_index in area_index_to_problem
                        }

                        # Emit per-problem detection outcomes. "multi_unexpected" flags
                        # single-select problems that came back with >1 answer — that
                        # is the per-problem failure signal an operator wants charted.
                        for problem_id, local_ids in problem_results.items():
                            problem = problem_map.get(problem_id)
                            if problem is None:
                                continue
                            allows_multi = multi_select_by_area_id.get(problem.exam_paper_area_id, False)
                            if not local_ids:
                                outcome = "blank"
                            elif len(local_ids) == 1:
                                outcome = "single"
                            elif allows_multi:
                                outcome = "multi_expected"
                            else:
                                outcome = "multi_unexpected"
                            telemetry.record_problem_outcome(
                                outcome=outcome,
                                exam_round_id=str(exam_round_id),
                                problem_index=problem.exam_paper_area.index if problem.exam_paper_area else None,
                            )

                        student_id = await self._derive_student_id(
                            process_result["student_info_results"],
                            identifier_areas,
                            logger=logger,
                        )
                        await logger.info(f"IDENTIFIER detections: {process_result['student_info_results']} -> studentId={student_id}")

                        # Calculate score for submission/draft
                        score = self._calculate_score(problem_results, problem_map)

                        # Stringify METADATA detections via choice_type.from_choices.
                        # The result is persisted as-is into DraftSubmission/ExamSubmission.metadata
                        # so confirmDraftSubmission can forward it through unchanged.
                        metadata_payload = await self._derive_metadata_payload(
                            process_result.get("metadata_results", {}),
                            metadata_areas,
                            logger=logger,
                        )

                        # A "valid" scan result has a resolved studentId, every problem answered,
                        # and multi-answers only on multi-select problems. Valid results skip the
                        # draft phase even when student verification is enabled.
                        is_valid_result = self._is_valid_scan_result(student_id, problem_results, problem_map, multi_select_by_area_id)

                        # An EXAM_NAME metadata area that did not resolve to a name
                        # forces a DraftSubmission so a human can fix it — except
                        # for TEACHER scans, which always go direct.
                        exam_name_unresolved = self._is_exam_name_unresolved(metadata_areas, metadata_payload)
                        force_draft_unresolved_name = self._force_draft_for_unresolved_name(exam_name_unresolved, scan_request_source)

                        # Branch based on studentVerificationEnabled, source, scan validity,
                        # and unresolved EXAM_NAME. Teacher scans and valid scans otherwise
                        # create ExamSubmission directly (skip draft phase).
                        recalculate_stats = False
                        if (exam.student_verification_enabled and scan_request_source != "TEACHER" and not is_valid_result) or force_draft_unresolved_name:
                            # Create DraftSubmission (student verification required, or
                            # EXAM_NAME unresolved on a non-teacher scan)
                            if force_draft_unresolved_name:
                                await logger.info("Forcing DraftSubmission: EXAM_NAME metadata unresolved (source != TEACHER)")
                            else:
                                await logger.info("Creating DraftSubmission (studentVerificationEnabled=true, source=STUDENT)")

                            # Check if this ScanRequest already has a draft or submission (single query with two EXISTS)
                            draft_exists = exists(
                                select(DraftSubmission.id)
                                .join(ScanRequestJob, DraftSubmission.scan_job_id == ScanRequestJob.id)
                                .where(
                                    ScanRequestJob.scan_request_id == scan_request_id,
                                    DraftSubmission.discarded_at.is_(None),
                                )
                            )
                            submission_exists = exists(
                                select(ExamSubmission.id)
                                .join(ScanRequestJob, ExamSubmission.scan_job_id == ScanRequestJob.id)
                                .where(
                                    ScanRequestJob.scan_request_id == scan_request_id,
                                    ExamSubmission.deleted_at.is_(None),
                                )
                            )
                            has_existing_result = await session.execute(select(draft_exists.label("has_draft"), submission_exists.label("has_submission")))
                            has_existing = has_existing_result.one()
                            if has_existing.has_draft or has_existing.has_submission:
                                await logger.info("Dropped: ScanRequest already has a draft or submission")
                                await session.execute(
                                    update(ScanRequestJob)
                                    .where(ScanRequestJob.id == job_id)
                                    .values(finished_at=now, result="SUCCESS", organization_id=process_result["organization_id"])
                                )
                                await session.commit()
                                scan_result = "success"
                                await profiler.log_summary(logger)
                                continue

                            # Check if confirmed ExamSubmission already exists for this examRound + studentId
                            existing_submission_for_student = await session.execute(
                                select(ExamSubmission.id)
                                .where(
                                    ExamSubmission.exam_round_id == exam_round_id,
                                    ExamSubmission.student_id == student_id,
                                    ExamSubmission.deleted_at.is_(None),
                                )
                                .limit(1)
                            )
                            if existing_submission_for_student.scalar_one_or_none() is not None:
                                if scan_request_source == "TEACHER":
                                    # Teacher scans take priority: soft-delete existing ExamSubmission
                                    await logger.info(f"Teacher scan: soft-deleting existing ExamSubmission for studentId={student_id}")
                                    submissions_to_delete_subquery = (
                                        select(ExamSubmission.id)
                                        .where(
                                            ExamSubmission.exam_round_id == exam_round_id,
                                            ExamSubmission.student_id == student_id,
                                            ExamSubmission.deleted_at.is_(None),
                                        )
                                        .scalar_subquery()
                                    )
                                    await session.execute(delete(ExamSubmissionAnswer).where(ExamSubmissionAnswer.exam_submission_id.in_(submissions_to_delete_subquery)))
                                    await session.execute(
                                        update(ExamSubmission)
                                        .where(
                                            ExamSubmission.exam_round_id == exam_round_id,
                                            ExamSubmission.student_id == student_id,
                                            ExamSubmission.deleted_at.is_(None),
                                        )
                                        .values(deleted_at=now)
                                    )
                                else:
                                    # Student scans fail if ExamSubmission already exists
                                    raise ProcessError(
                                        f"ExamSubmission already exists for studentId={student_id}",
                                        code="EXAM_SUBMISSION_ALREADY_EXISTS",
                                        params={"student_id": student_id, "exam_round_id": str(exam_round_id)},
                                    )

                            # Soft-delete (discard) previous drafts for this examRound + studentId (single UPDATE with subquery)
                            discard_result = cast(
                                CursorResult[tuple[()]],
                                await session.execute(
                                    update(DraftSubmission)
                                    .where(
                                        DraftSubmission.exam_round_id == exam_round_id,
                                        DraftSubmission.student_id == student_id,
                                        DraftSubmission.discarded_at.is_(None),
                                        DraftSubmission.confirmed_at.is_(None),
                                    )
                                    .values(discarded_at=now)
                                ),
                            )
                            if discard_result.rowcount > 0:
                                await logger.info(f"Discarded {discard_result.rowcount} previous draft(s) for studentId={student_id}")

                            # Create DraftSubmission
                            draft_submission = DraftSubmission(
                                id=uuid7.create(),
                                organization_id=process_result["organization_id"],
                                exam_round_id=exam_round_id,
                                scan_job_id=job_id,
                                student_id=student_id,
                                score=score,
                                metadata_=metadata_payload,
                                updated_at=now,
                            )
                            session.add(draft_submission)

                            # Create DraftSubmissionAnswers for each problem
                            for problem_id, local_ids in problem_results.items():
                                draft_submission_answer = DraftSubmissionAnswer(
                                    id=uuid7.create(),
                                    draft_submission_id=draft_submission.id,
                                    problem_id=problem_id,
                                    value=local_ids if local_ids else None,
                                )
                                session.add(draft_submission_answer)

                            # Note: Statistics are NOT recalculated for drafts
                        else:
                            # Create ExamSubmission directly (teacher scan, valid student scan, or verification disabled)
                            if scan_request_source == "TEACHER":
                                await logger.info("Creating ExamSubmission (source=TEACHER, bypassing draft phase)")
                            elif exam.student_verification_enabled and is_valid_result:
                                await logger.info("Creating ExamSubmission (valid scan result, bypassing draft phase)")
                            else:
                                await logger.info("Creating ExamSubmission (studentVerificationEnabled=false)")

                            # Check 1: Skip if this ScanRequest already has a successful submission
                            existing_for_request = await session.execute(
                                select(ExamSubmission.id)
                                .join(ScanRequestJob, ExamSubmission.scan_job_id == ScanRequestJob.id)
                                .where(
                                    ScanRequestJob.scan_request_id == scan_request_id,
                                    ExamSubmission.deleted_at.is_(None),
                                )
                                .limit(1)
                            )
                            if existing_for_request.scalar_one_or_none() is not None:
                                await logger.info("Dropped: ScanRequest already has a successful submission")
                                await session.execute(
                                    update(ScanRequestJob)
                                    .where(ScanRequestJob.id == job_id)
                                    .values(finished_at=now, result="SUCCESS", organization_id=process_result["organization_id"])
                                )
                                await session.commit()
                                scan_result = "success"
                                await profiler.log_summary(logger)
                                continue

                            # Check if ExamSubmission already exists for this examRound + studentId
                            existing_submission_for_student = await session.execute(
                                select(ExamSubmission.id)
                                .where(
                                    ExamSubmission.exam_round_id == exam_round_id,
                                    ExamSubmission.student_id == student_id,
                                    ExamSubmission.deleted_at.is_(None),
                                )
                                .limit(1)
                            )
                            if existing_submission_for_student.scalar_one_or_none() is not None:
                                if scan_request_source == "TEACHER":
                                    # Teacher scans take priority: soft-delete existing ExamSubmission
                                    await logger.info(f"Teacher scan: soft-deleting existing ExamSubmission for studentId={student_id}")
                                    submissions_to_delete_subquery = (
                                        select(ExamSubmission.id)
                                        .where(
                                            ExamSubmission.exam_round_id == exam_round_id,
                                            ExamSubmission.student_id == student_id,
                                            ExamSubmission.deleted_at.is_(None),
                                        )
                                        .scalar_subquery()
                                    )
                                    await session.execute(delete(ExamSubmissionAnswer).where(ExamSubmissionAnswer.exam_submission_id.in_(submissions_to_delete_subquery)))
                                    await session.execute(
                                        update(ExamSubmission)
                                        .where(
                                            ExamSubmission.exam_round_id == exam_round_id,
                                            ExamSubmission.student_id == student_id,
                                            ExamSubmission.deleted_at.is_(None),
                                        )
                                        .values(deleted_at=now)
                                    )
                                else:
                                    # Student scans fail if ExamSubmission already exists
                                    raise ProcessError(
                                        f"ExamSubmission already exists for studentId={student_id}",
                                        code="EXAM_SUBMISSION_ALREADY_EXISTS",
                                        params={"student_id": student_id, "exam_round_id": str(exam_round_id)},
                                    )

                            # Also discard any pending DraftSubmissions for this student (in case verification was enabled)
                            discard_draft_result = cast(
                                CursorResult[tuple[()]],
                                await session.execute(
                                    update(DraftSubmission)
                                    .where(
                                        DraftSubmission.exam_round_id == exam_round_id,
                                        DraftSubmission.student_id == student_id,
                                        DraftSubmission.discarded_at.is_(None),
                                        DraftSubmission.confirmed_at.is_(None),
                                    )
                                    .values(discarded_at=now)
                                ),
                            )
                            if discard_draft_result.rowcount > 0:
                                await logger.info(f"Discarded {discard_draft_result.rowcount} previous draft(s) for studentId={student_id}")

                            # Create ExamSubmission
                            exam_submission = ExamSubmission(
                                id=uuid7.create(),
                                organization_id=process_result["organization_id"],
                                exam_round_id=exam_round_id,
                                scan_job_id=job_id,
                                student_id=student_id,
                                score=score,
                                metadata_=metadata_payload,
                                updated_at=now,
                            )
                            session.add(exam_submission)

                            # Create ExamSubmissionAnswers for each problem
                            for problem_id, local_ids in problem_results.items():
                                exam_submission_answer = ExamSubmissionAnswer(
                                    id=uuid7.create(),
                                    exam_submission_id=exam_submission.id,
                                    problem_id=problem_id,
                                    value=local_ids if local_ids else None,
                                )
                                session.add(exam_submission_answer)

                            # Defer statistics recalculation until after commit so the
                            # backend's read transaction sees the new ExamSubmission rows.
                            recalculate_stats = is_valid_student_id(student_id)

                        await session.execute(
                            update(ScanRequestJob).where(ScanRequestJob.id == job_id).values(finished_at=now, result="SUCCESS", organization_id=process_result["organization_id"])
                        )
                        await session.execute(update(ScanRequest).where(ScanRequest.id == scan_request_id).values(success_at=now))
                        await session.commit()
                        scan_result = "success"

                        if recalculate_stats:
                            api_client = get_api_client()
                            if api_client is not None:
                                # Submission is already committed; isolate stats-refresh
                                # failures so a transient API outage cannot mislabel the
                                # scan as FAILED via the outer exception handlers.
                                try:
                                    await api_client.recalculate_exam_round_statistics(exam_round_id)
                                    await api_client.recalculate_exam_statistics(exam_id)
                                except Exception as stats_error:
                                    await logger.warn(f"Statistics recalculation failed after successful submission: {stats_error}")

                    # Log timing summary
                    await profiler.log_summary(logger)
                except ProcessError as e:
                    scan_error_code = e.code
                    await logger.error(e.message)
                    now = datetime.now()
                    await session.execute(
                        update(ScanRequestJob)
                        .where(ScanRequestJob.id == job_id)
                        .values(
                            finished_at=now,
                            result="FAILED",
                            organization_id=organization_id,
                            result_code=e.code,
                            result_params=e.params,
                        )
                    )
                    await session.execute(update(ScanRequest).where(ScanRequest.id == scan_request_id).values(failed_at=now))
                    await session.commit()
                except IntegrityError as e:
                    await session.rollback()
                    # Handle unique constraint violations on submissions
                    error_str = str(e.orig) if e.orig else str(e)
                    if "ExamSubmission_examRoundId_studentId_unique_active" in error_str:
                        error_code = "EXAM_SUBMISSION_ALREADY_EXISTS"
                        error_message = "An active exam submission already exists for this student and exam round (concurrent request)"
                    elif "DraftSubmission_examRoundId_studentId_unique_pending" in error_str:
                        error_code = "DRAFT_SUBMISSION_ALREADY_EXISTS"
                        error_message = "A pending draft submission already exists for this student and exam round (concurrent request)"
                    else:
                        error_code = "DATABASE_CONSTRAINT_VIOLATION"
                        error_message = f"Database constraint violation: {error_str}"

                    scan_error_code = error_code
                    await logger.error(error_message)
                    now = datetime.now()
                    await session.execute(
                        update(ScanRequestJob)
                        .where(ScanRequestJob.id == job_id)
                        .values(
                            finished_at=now,
                            result="FAILED",
                            organization_id=organization_id,
                            result_code=error_code,
                            result_params={"error": error_str},
                        )
                    )
                    await session.execute(update(ScanRequest).where(ScanRequest.id == scan_request_id).values(failed_at=now))
                    await session.commit()
                except Exception as e:
                    scan_error_code = "UNKNOWN_ERROR"
                    await logger.error(f"Processing failed with unknown error: {e}")
                    now = datetime.now()
                    await session.execute(
                        update(ScanRequestJob)
                        .where(ScanRequestJob.id == job_id)
                        .values(
                            finished_at=now,
                            result="FAILED",
                            organization_id=organization_id,
                            result_code="UNKNOWN_ERROR",
                            result_params={"error": str(e)},
                        )
                    )
                    await session.execute(update(ScanRequest).where(ScanRequest.id == scan_request_id).values(failed_at=now))
                    await session.commit()
                finally:
                    # Cleanup processed images after job completion (but not background images)
                    self._cleanup_processed_images(scan_request_id, job_id, scan_request_key)
                    telemetry.record_scan(
                        (time.perf_counter() - scan_start) * 1000,
                        result=scan_result,
                        error_code=scan_error_code,
                        processor_version=processor_version,
                        source=scan_request_source,
                    )
                    telemetry.end_current_span(
                        scan_span,
                        scan_span_token,
                        error=scan_error_code if scan_result != "success" else None,
                        **{
                            "scan.result": scan_result,
                            "scan.error_code": scan_error_code,
                            "scan.processor_version": (str(processor_version) if processor_version is not None else None),
                        },
                    )
