from __future__ import annotations

import os
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from zxingcpp import Barcode, BarcodeFormat, BarcodeFormats, read_barcodes

from worker.loggers.console import ConsoleLogger

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

from ..consts import BASE64_URL_REGEX, POSITIONS
from ..generated.models import Exam, ExamPaper, ExamPaperArea, ExamRound, PaperType
from ..loggers import BaseLogger
from ..paths import get_result_path, get_results_dir
from ..profiler import JobProfiler
from ..processor_observer import ProcessorObserver
from ..types import UUID, Annotations, ImageProcessingParams, ProcessError, ProcessResult
from ..util import base64url_to_uuid, get_barcode_corners, get_by_id


class BaseProcessor(ABC):
    def __init__(self, client: S3Client, bucket_name: str, engine: AsyncEngine):
        self.client = client
        self.bucket_name = bucket_name
        self.engine = engine
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._logger: BaseLogger = ConsoleLogger()
        self._profiler: JobProfiler | None = None
        # No-op observer by default; ProcessorV1.process() rebinds this to a
        # DebugObserver when ImageProcessingParams.debug is set.
        self._observer: ProcessorObserver = ProcessorObserver()

    def set_logger(self, logger: BaseLogger):
        self._logger = logger

    def set_profiler(self, profiler: JobProfiler):
        self._profiler = profiler

    @contextmanager
    def _time(self, name: str):
        """Time a synchronous operation. No-op if profiler is not set."""
        if not self._profiler:
            yield
            return
        with self._profiler.time(name):
            yield

    @asynccontextmanager
    async def _time_async(self, name: str):
        """Time an async operation. No-op if profiler is not set."""
        if not self._profiler:
            yield
            return
        async with self._profiler.time_async(name):
            yield

    def _detect_qrcode(self, image: cv2.typing.MatLike):
        detected = read_barcodes(image, formats=BarcodeFormats(BarcodeFormat.QRCode))

        annotations: list[Annotations] = []

        if len(detected) != 1:
            raise ProcessError(
                f"Expected 1 QR code, but found {len(detected)}",
                code="QR_CODE_COUNT_MISMATCH",
                params={"expected": 1, "found": len(detected)},
            )

        try:
            url = urlparse(detected[0].text)
            params = parse_qs(url.query)
        except AttributeError:
            raise ProcessError(
                f"Invalid QR code content: {detected[0].text}",
                code="QR_CODE_INVALID_CONTENT",
                params={"content": detected[0].text},
            )

        if "e" not in params:
            raise ProcessError(
                f"Missing exam round id in QR code content: {detected[0].text}",
                code="QR_CODE_MISSING_EXAM_ROUND",
                params={"content": detected[0].text},
            )

        if "a" not in params:
            raise ProcessError(
                f"Missing positional QR code data in QR code content: {detected[0].text}",
                code="QR_CODE_MISSING_AREA",
                params={"content": detected[0].text},
            )

        if len(params["e"]) != 1:
            raise ProcessError(
                f"Invalid exam round id in QR code content: {detected[0].text}",
                code="QR_CODE_INVALID_EXAM_ROUND",
                params={"content": detected[0].text},
            )

        if len(params["a"]) != 1:
            raise ProcessError(
                f"Invalid positional QR code data in QR code content: {detected[0].text}",
                code="QR_CODE_INVALID_AREA",
                params={"content": detected[0].text},
            )

        if len(params["a"][0]) != 22 or BASE64_URL_REGEX.match(params["a"][0]) is None:
            raise ProcessError(
                f"Invalid positional QR code data format in QR code content: {detected[0].text}",
                code="QR_CODE_INVALID_AREA_FORMAT",
                params={"content": detected[0].text},
            )

        if len(params["e"][0]) != 22 or BASE64_URL_REGEX.match(params["e"][0]) is None:
            raise ProcessError(
                f"Invalid exam round id format in QR code content: {detected[0].text}",
                code="QR_CODE_INVALID_EXAM_ROUND_FORMAT",
                params={"content": detected[0].text},
            )

        annotations.append(Annotations(data=np.array([get_barcode_corners(detected[0], pos) for pos in POSITIONS], dtype=np.int32), type="qrcode_detected", value=detected[0].text))

        return detected[0], annotations, base64url_to_uuid(params["e"][0]), base64url_to_uuid(params["a"][0])

    def _detect_all_qrcodes(self, image: cv2.typing.MatLike) -> dict[UUID, Barcode]:
        """Detect all QR codes in the image and return them indexed by area_id.

        Each QR code contains an 'a' parameter with the area_id it belongs to.
        This method parses all detected QR codes and returns a mapping from
        area_id to the corresponding Barcode object.

        Args:
            image: The scan image to detect QR codes in

        Returns:
            Dictionary mapping area_id (UUID) to Barcode object
        """
        detected = read_barcodes(image, formats=BarcodeFormats(BarcodeFormat.QRCode))
        qrcode_map: dict[UUID, Barcode] = {}

        for barcode in detected:
            try:
                url = urlparse(barcode.text)
                params = parse_qs(url.query)

                if "a" not in params or len(params["a"]) != 1:
                    continue

                area_id_str = params["a"][0]
                if len(area_id_str) != 22 or BASE64_URL_REGEX.match(area_id_str) is None:
                    continue

                area_id = base64url_to_uuid(area_id_str)
                qrcode_map[area_id] = barcode
            except (AttributeError, ValueError):
                continue

        return qrcode_map

    async def _get_database_records(self, session: AsyncSession, exam_round_id: UUID, area_id: UUID):
        exam_round = await get_by_id(session, ExamRound, exam_round_id)

        if exam_round is None:
            raise ProcessError(
                f"Exam round not found with id {exam_round_id}",
                code="EXAM_ROUND_NOT_FOUND",
                params={"exam_round_id": str(exam_round_id)},
            )
        exam = await get_by_id(session, Exam, exam_round.exam_id)
        if exam is None:
            raise ProcessError(
                f"Exam not found with id {exam_round.exam_id}",
                code="EXAM_NOT_FOUND",
                params={"exam_id": str(exam_round.exam_id)},
            )

        exam_paper = await get_by_id(session, ExamPaper, exam.exam_paper_id)
        if exam_paper is None:
            raise ProcessError(
                f"Exam paper not found with id {exam.exam_paper_id}",
                code="EXAM_PAPER_NOT_FOUND",
                params={"exam_paper_id": str(exam.exam_paper_id)},
            )

        area_result = await session.execute(select(ExamPaperArea).where(ExamPaperArea.id == area_id, ExamPaperArea.exam_paper_id == exam_paper.id))
        area = area_result.scalar_one_or_none()
        if area is None:
            raise ProcessError(
                f"Exam paper area not found with id {area_id}",
                code="EXAM_PAPER_AREA_NOT_FOUND",
                params={"area_id": str(area_id)},
            )

        paper_type = await get_by_id(session, PaperType, exam_paper.paper_type_id)
        if paper_type is None:
            raise ProcessError(
                f"Paper type not found with id {exam_paper.paper_type_id}",
                code="PAPER_TYPE_NOT_FOUND",
                params={"paper_type_id": str(exam_paper.paper_type_id)},
            )

        areas_result = await session.execute(select(ExamPaperArea).where(ExamPaperArea.exam_paper_id == exam_paper.id).options(selectinload(ExamPaperArea.area_type)))
        areas = areas_result.scalars().all()
        return exam_round, exam, exam_paper, paper_type, area, areas

    def _save_area_image(self, request_id: UUID, job_id: UUID, image: cv2.typing.MatLike, filename: str) -> str:
        os.makedirs(get_results_dir(request_id, job_id), exist_ok=True)
        path = get_result_path(request_id, job_id, f"{filename}.png")
        # Handle grayscale images (from threshold) vs RGB images
        if len(image.shape) == 2:
            cv2.imwrite(path, image)
        else:
            cv2.imwrite(path, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        return path

    def _annotated_image(
        self,
        image: cv2.typing.MatLike,
        annotations: list[Annotations],
        params: ImageProcessingParams,
    ) -> cv2.typing.MatLike:
        annotated = image.copy()
        for annotation in annotations:
            if annotation["type"] == "qrcode_detected":
                color = (255, 0, 0)
            elif annotation["value"].startswith("IDENTIFIER"):
                color = (0, 255, 0)  # Green for identifier/student info areas
            elif annotation["value"].startswith("PROBLEM"):
                color = (255, 165, 0)  # Orange for problem areas
            else:
                color = (0, 0, 0)
            cv2.polylines(annotated, [annotation["data"]], isClosed=True, color=color, thickness=params.annotation_thickness)
        return annotated

    def _parse_processing_params(self, metadata: dict) -> ImageProcessingParams:
        """Parse image processing params from metadata, using defaults if not present."""
        params_data = metadata.get("processing_params", {})
        return ImageProcessingParams.model_validate(params_data)

    @abstractmethod
    async def process(self, image: cv2.typing.MatLike, job_id: UUID, request_id: UUID, metadata: dict) -> ProcessResult:
        """Process the image and return results. To be implemented by version-specific processors."""
        pass
