"""Modal L4 entrypoint for ShelfAlign YOLO OBB and PaddleOCR inference.

Deploy from the repository root with:
    python -m modal deploy modal_app.py
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

import modal
from pydantic import BaseModel, Field

APP_NAME = "shelfalign-vision"
REMOTE_ROOT = Path("/opt/shelfalign")
MODEL_PATH = REMOTE_ROOT / "worker/models/book_spine_run/weights/best.pt"

gpu_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04",
        add_python="3.12",
    )
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "torch",
        "torchvision",
        index_url="https://download.pytorch.org/whl/cu126",
    )
    .pip_install(
        "paddlepaddle-gpu==3.3.0",
        index_url="https://www.paddlepaddle.org.cn/packages/stable/cu126/",
        extra_index_url="https://pypi.org/simple",
        extra_options="--no-deps",
    )
    .pip_install(
        "ultralytics>=8.3,<9",
        "paddleocr>=3.3,<4",
        "opencv-python-headless>=4.12,<5",
        "pydantic-settings>=2.12,<3",
        "fastapi[standard]>=0.127,<1",
        "httpx>=0.28,<1",
        "opt-einsum==3.3.0",
        "protobuf>=3.20.2",
        "safetensors>=0.6,<1",
        "nvidia-cuda-cccl-cu12==12.6.77",
    )
    .add_local_dir("worker", remote_path="/opt/shelfalign/worker", copy=True)
)

model_cache = modal.Volume.from_name("shelfalign-paddle-models", create_if_missing=True)
app = modal.App(APP_NAME)


class VisionInput(BaseModel):
    image_base64: str
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


@app.cls(
    image=gpu_image,
    gpu="L4",
    min_containers=0,
    max_containers=1,
    scaledown_window=20,
    timeout=180,
    startup_timeout=300,
    volumes={"/root/.paddlex": model_cache},
)
class ShelfAlignVision:
    @modal.enter()
    def setup(self) -> None:
        os.chdir(REMOTE_ROOT)
        sys.path.insert(0, str(REMOTE_ROOT))
        os.environ["PADDLE_OCR_DEVICE"] = "gpu:0"

        from worker.services.detection_service import detector_service
        from worker.services.vision_service import vision_service

        if not detector_service.is_ready:
            raise RuntimeError(f"YOLO model is not ready at {MODEL_PATH}")
        if vision_service.ocr is None:
            raise RuntimeError("PaddleOCR GPU engine did not initialize.")

        self.detector = detector_service
        self.vision = vision_service
        self.model_sha256 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
        model_cache.commit()

    def _analyze(self, request: VisionInput) -> VisionOutput:
        from worker.services.ocr_field_parser import extract_ocr_fields

        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
        except ValueError as exc:
            raise ValueError("image_base64 is invalid.") from exc

        with tempfile.TemporaryDirectory(prefix="shelfalign-") as directory:
            image_path = Path(directory) / "shelf-image.jpg"
            image_path.write_bytes(image_bytes)

            detection_started = time.perf_counter()
            detections = self.detector.detect_spines(str(image_path))
            detection_seconds = time.perf_counter() - detection_started

            ocr_started = time.perf_counter()
            grouped, metadata = self.vision.crop_many_for_fast_ocr(
                str(image_path),
                [(item.bbox, item.polygon if item.is_obb else None) for item in detections],
            )
            items: list[VisionItem] = []
            for order, (detection, extracted, crop) in enumerate(
                zip(detections, grouped, metadata, strict=True),
                start=1,
            ):
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

    @modal.method()
    def infer(self, request: VisionInput) -> VisionOutput:
        return self._analyze(request)

    @modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
    def analyze(self, request: VisionInput) -> VisionOutput:
        return self._analyze(request)


@app.local_entrypoint()
def smoke(image_path: str) -> None:
    """Run one authenticated smoke request without exposing proxy credentials."""

    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    result = ShelfAlignVision().infer.remote(VisionInput(image_base64=encoded, adaptive=False))
    print(
        f"spines={len(result.items)} detection={result.detection_seconds:.2f}s "
        f"ocr={result.ocr_seconds:.2f}s model_sha256={result.model_sha256}"
    )
