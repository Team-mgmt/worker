"""fal Serverless GPU entrypoint for ShelfAlign detection and OCR.

Deploy from the repository root with:
    fal deploy fal_app.py::ShelfAlignVision --app-name shelfalign-vision
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import fal
from fal.container import ContainerImage
from pydantic import BaseModel, Field

MODEL_PATH = Path("worker/models/book_spine_run/weights/best.pt")

GPU_IMAGE = ContainerImage.from_dockerfile_str(
    """
    FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04
    ENV DEBIAN_FRONTEND=noninteractive
    RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libgl1 libglib2.0-0 python3 python3-pip python3-venv \
        && rm -rf /var/lib/apt/lists/*
    RUN python3 -m venv /opt/venv
    ENV PATH=/opt/venv/bin:$PATH
    RUN pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cu126
    RUN pip install --no-cache-dir paddlepaddle-gpu==3.3.0 \
        --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
        --extra-index-url https://pypi.org/simple
    RUN pip install --no-cache-dir \
        'ultralytics>=8.3,<9' 'paddleocr>=3.3,<4' \
        'opencv-python-headless>=4.12,<5' 'pydantic-settings>=2.12,<3'
    RUN pip install --no-cache-dir fal
    WORKDIR /app
    COPY worker /app/worker
    """,
    context_dir=Path(__file__).parent,
    dockerignore=[".git", ".env", ".venv", "outputs", "web", "tests", "*.jpg", "*.png"],
)


class VisionInput(BaseModel):
    image_url: str
    adaptive: bool = True


class VisionItem(BaseModel):
    detected_order: int
    raw_text: str
    title: str | None = None
    author: str | None = None
    call_number: str | None = None
    bbox: list[float]
    ocr_confidence: float | None = None
    detection_confidence: float | None = None
    obb_polygon: list[list[float]] | None = None
    crop_method: str | None = None
    crop_size: list[int] | None = None
    ocr_variant: str | None = None
    ocr_attempt_count: int | None = None
    ocr_label_text: str | None = None
    ocr_label_confidence: float | None = None


class VisionOutput(BaseModel):
    items: list[VisionItem]
    detection_seconds: float = Field(ge=0.0)
    ocr_seconds: float = Field(ge=0.0)
    model_sha256: str


class ShelfAlignVision(fal.App, keep_alive=20, min_concurrency=0, max_concurrency=1):
    machine_type = "GPU-RTX4090"
    image = GPU_IMAGE

    def setup(self) -> None:
        os.environ["PADDLE_OCR_DEVICE"] = "gpu:0"
        from worker.services.detection_service import detector_service
        from worker.services.vision_service import vision_service

        if not detector_service.is_ready:
            raise RuntimeError(f"YOLO model is not ready at {MODEL_PATH}")
        self.detector = detector_service
        self.vision = vision_service
        self.model_sha256 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()

    @fal.endpoint("/")
    def analyze(self, request: VisionInput) -> VisionOutput:
        from worker.services.ocr_field_parser import extract_ocr_fields

        with tempfile.TemporaryDirectory(prefix="shelfalign-") as directory:
            image_path = Path(directory) / "shelf-image"
            with urlopen(request.image_url, timeout=30) as response:
                image_path.write_bytes(response.read())

            detection_started = time.perf_counter()
            detections = self.detector.detect_spines(str(image_path))
            detection_seconds = time.perf_counter() - detection_started

            ocr_started = time.perf_counter()
            grouped, metadata = self.vision.crop_many_for_fast_ocr(
                str(image_path),
                [(item.bbox, item.polygon if item.is_obb else None) for item in detections],
            )
            items: list[VisionItem] = []
            for order, (detection, extracted, crop) in enumerate(zip(detections, grouped, metadata, strict=True), start=1):
                raw_text = self.vision._join_text(extracted)
                if request.adaptive and (
                    not extracted
                    or (self.vision._average_confidence(extracted) or 0.0) < 0.78
                    or not self.vision._has_call_number(raw_text)
                ):
                    extracted, crop = self.vision.crop_and_ocr(
                        str(image_path),
                        crop_rect=detection.bbox,
                        obb_polygon=detection.polygon if detection.is_obb else None,
                        adaptive=True,
                    )
                    raw_text = self.vision._join_text(extracted)

                title, author, call_number = extract_ocr_fields(raw_text)
                x, y, width, height = detection.bbox
                items.append(
                    VisionItem(
                        detected_order=order,
                        raw_text=raw_text,
                        title=title,
                        author=author,
                        call_number=call_number or None,
                        bbox=[float(x), float(y), float(x + width), float(y + height)],
                        ocr_confidence=self.vision._average_confidence(extracted),
                        detection_confidence=detection.confidence,
                        obb_polygon=detection.polygon,
                        crop_method=crop.method,
                        crop_size=crop.size,
                        ocr_variant=crop.ocr_variant,
                        ocr_attempt_count=crop.attempt_count,
                        ocr_label_text=crop.label_text,
                        ocr_label_confidence=crop.label_confidence,
                    )
                )

        return VisionOutput(
            items=items,
            detection_seconds=detection_seconds,
            ocr_seconds=time.perf_counter() - ocr_started,
            model_sha256=self.model_sha256,
        )
