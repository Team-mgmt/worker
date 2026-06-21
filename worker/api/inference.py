import json
import os
from pathlib import Path

from PIL import Image
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from worker.core.database import get_db
from worker.schemas.inference import MatchResponse, OCRResultItem, ScanSessionRequest
from worker.services.inference_service import process_scan_session_request

router = APIRouter(prefix="/inference", tags=["Inference"])

TEST_IMAGES_DIR = Path(__file__).resolve().parents[1] / "tests" / "test_images"
BBOXES_JSON = Path(__file__).resolve().parents[1] / "tests" / "bboxes.json"


@router.post("/scan", response_model=MatchResponse)
async def process_scan_session(request: ScanSessionRequest, db: AsyncSession = Depends(get_db)):
    return await process_scan_session_request(request, db)


@router.post("/upload_demo", response_model=MatchResponse)
async def upload_demo(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")

    os.makedirs("outputs", exist_ok=True)
    temp_path = Path("outputs") / filename
    with temp_path.open("wb") as f:
        f.write(await file.read())

    if not BBOXES_JSON.exists():
        raise HTTPException(status_code=500, detail="bboxes.json not found")

    with BBOXES_JSON.open("r", encoding="utf-8") as f:
        bboxes_data = json.load(f)

    matched_key = None
    for key in bboxes_data:
        if filename in key or key in filename:
            matched_key = key
            break

    if not matched_key:
        matched_key = "nowon_shelf_real_001.jpg"

    from worker.services.vision_service import vision_service

    ocr_results_payload = []
    pristine_img_path = TEST_IMAGES_DIR / matched_key

    for i, box_info in enumerate(bboxes_data[matched_key]):
        x, y, w, h = box_info["bbox"]
        try:
            extracted = vision_service.manual_crop_and_ocr(str(pristine_img_path), (x, y, w, h), preprocess=True)
            text = " ".join([res["text"] for res in extracted])
            confidence = sum([res["confidence"] for res in extracted]) / len(extracted) if extracted else 0.0
        except Exception as exc:
            print(f"OCR error for box {i}: {exc}")
            text = ""
            confidence = 0.0

        ocr_results_payload.append(
            OCRResultItem(
                detected_order=i + 1,
                raw_text=text,
                title=box_info.get("expected_title"),
                call_number=text,
                bbox=[x, y, x + w, y + h],
                crop_image_path=None,
                ocr_confidence=confidence,
            )
        )

    req = ScanSessionRequest(
        library_code="111058",
        room_name="Nowon Jungang Library",
        source_name=filename,
        ocr_results=ocr_results_payload,
    )

    return await process_scan_session_request(req, db, persist=False)


@router.post("/analyze_yolo", response_model=MatchResponse)
async def analyze_yolo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    conf_threshold: float = 0.35,
    preprocess: bool = True,
    library_code: str = "111058",
    room_name: str = "노원중앙도서관 종합자료실",
):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")

    from worker.services.detection_service import detector_service

    if not detector_service.is_ready:
        raise HTTPException(
            status_code=503,
            detail=f"Book-spine YOLO model is not ready. Expected model at {detector_service.model_path}.",
        )

    os.makedirs("outputs/uploads", exist_ok=True)
    safe_filename = Path(filename).name
    temp_path = Path("outputs/uploads") / safe_filename
    with temp_path.open("wb") as f:
        f.write(await file.read())

    try:
        boxes = detector_service.detect_spines(str(temp_path), conf_threshold=conf_threshold)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"YOLO detection failed: {exc}") from exc

    from worker.services.vision_service import vision_service

    ocr_results_payload = []
    for index, (x, y, w, h) in enumerate(boxes, start=1):
        try:
            extracted = vision_service.manual_crop_and_ocr(str(temp_path), (x, y, w, h), preprocess=preprocess)
            text = " ".join([res["text"] for res in extracted])
            confidence = sum([res["confidence"] for res in extracted]) / len(extracted) if extracted else 0.0
        except Exception as exc:
            print(f"OCR error for YOLO box {index}: {exc}")
            text = ""
            confidence = 0.0

        ocr_results_payload.append(
            OCRResultItem(
                detected_order=index,
                raw_text=text,
                call_number=text,
                bbox=[x, y, x + w, y + h],
                crop_image_path=None,
                ocr_confidence=confidence,
            )
        )

    req = ScanSessionRequest(
        library_code=library_code,
        room_name=room_name,
        source_name=safe_filename,
        ocr_results=ocr_results_payload,
    )

    return await process_scan_session_request(req, db, persist=False)


@router.get("/analyze_yolo")
async def analyze_yolo_status():
    from worker.services.detection_service import detector_service

    return {
        "ok": True,
        "method": "POST",
        "content_type": "multipart/form-data",
        "field": "file",
        "model_ready": detector_service.is_ready,
        "model_path": detector_service.model_path,
        "message": "Upload a shelf image with POST /inference/analyze_yolo.",
    }


def normalized_bbox_to_pixels(bbox: list[float], image_width: int, image_height: int) -> list[float]:
    x1, y1, x2, y2 = bbox
    return [
        max(0.0, min(image_width, (x1 / 1000.0) * image_width)),
        max(0.0, min(image_height, (y1 / 1000.0) * image_height)),
        max(0.0, min(image_width, (x2 / 1000.0) * image_width)),
        max(0.0, min(image_height, (y2 / 1000.0) * image_height)),
    ]


@router.post("/analyze_vlm", response_model=MatchResponse)
async def analyze_vlm(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    library_code: str = "111058",
    room_name: str = "노원중앙도서관 종합자료실",
):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")

    os.makedirs("outputs/uploads", exist_ok=True)
    safe_filename = Path(filename).name
    temp_path = Path("outputs/uploads") / safe_filename
    with temp_path.open("wb") as f:
        f.write(await file.read())

    from worker.services.vlm_service import VLMServiceError, analyze_shelf_image_with_vlm

    try:
        with Image.open(temp_path) as image:
            image_width, image_height = image.size
        vlm_result = await analyze_shelf_image_with_vlm(temp_path)
    except VLMServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"VLM analysis failed: {exc}") from exc

    ocr_results_payload = []
    for spine in vlm_result.spines:
        bbox = normalized_bbox_to_pixels(spine.bbox, image_width, image_height)
        ocr_results_payload.append(
            OCRResultItem(
                detected_order=spine.order,
                raw_text=spine.raw_text or "",
                title=spine.title,
                author=spine.author,
                call_number=spine.call_number or spine.raw_text or "",
                bbox=bbox,
                crop_image_path=None,
                ocr_confidence=spine.confidence,
            )
        )

    req = ScanSessionRequest(
        library_code=library_code,
        room_name=room_name,
        source_name=safe_filename,
        ocr_results=ocr_results_payload,
    )

    return await process_scan_session_request(req, db, persist=False)


@router.get("/analyze_vlm")
async def analyze_vlm_status():
    from worker.core.config import settings

    return {
        "ok": True,
        "method": "POST",
        "content_type": "multipart/form-data",
        "field": "file",
        "model": settings.VLM_MODEL,
        "api_base_url": settings.VLM_API_BASE_URL,
        "api_key_ready": bool(settings.VLM_API_KEY or settings.OPENAI_API_KEY),
        "message": "Upload a shelf image with POST /inference/analyze_vlm.",
    }
