import json
import os
import re
import time
from uuid import uuid4
from pathlib import Path

from PIL import Image
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from worker.core.database import get_db
from worker.schemas.inference import MatchResponse, OCRResultItem, ScanSessionRequest
from worker.services.detection_service import SpineDetection, detector_service
from worker.services.inference_service import process_scan_session_request
from worker.services.ocr_field_parser import extract_ocr_fields
from worker.services.scan_artifact_service import scan_artifact_service

router = APIRouter(prefix="/inference", tags=["Inference"])

TEST_IMAGES_DIR = Path(__file__).resolve().parents[1] / "tests" / "test_images"
BBOXES_JSON = Path(__file__).resolve().parents[1] / "tests" / "bboxes.json"
ANALYZE_LOG_PATH = Path("outputs") / "analyze_vlm.log"


def analyze_log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    try:
        os.makedirs(ANALYZE_LOG_PATH.parent, exist_ok=True)
        with ANALYZE_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
    except Exception:
        pass


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
        matched_key = "nowon_shelf_real_002.jpg"

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
    for index, detection in enumerate(boxes, start=1):
        x, y, w, h = detection.bbox
        try:
            extracted, crop_metadata = vision_service.crop_and_ocr(
                str(temp_path),
                crop_rect=(x, y, w, h),
                obb_polygon=detection.polygon if detection.is_obb else None,
                preprocess=preprocess,
            )
            text = " ".join([res["text"] for res in extracted])
            confidence = sum([res["confidence"] for res in extracted]) / len(extracted) if extracted else 0.0
        except Exception as exc:
            print(f"OCR error for YOLO box {index}: {exc}")
            text = ""
            confidence = 0.0
            crop_metadata = None

        title, author, call_number = extract_ocr_fields(text)

        ocr_results_payload.append(
            OCRResultItem(
                detected_order=index,
                raw_text=text,
                title=title,
                author=author,
                call_number=call_number,
                bbox=[x, y, x + w, y + h],
                crop_image_path=None,
                ocr_confidence=confidence,
                detection_confidence=detection.confidence,
                obb_polygon=detection.polygon,
                crop_method=crop_metadata.method if crop_metadata else None,
                crop_size=crop_metadata.size if crop_metadata else None,
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


@router.post("/analyze_vision", response_model=MatchResponse)
async def analyze_vision(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    library_code: str = "111058",
    room_name: str = "노원중앙도서관 종합자료실",
    preprocess: bool = False,
):
    request_started_at = time.perf_counter()
    run_id = str(uuid4())
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")

    safe_filename = Path(filename).name
    upload_dir = Path("outputs/uploads") / run_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / safe_filename
    with temp_path.open("wb") as f:
        f.write(await file.read())

    try:
        with Image.open(temp_path) as image:
            image_width, image_height = image.size
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {exc}")

    detections = []
    detection_started_at = time.perf_counter()
    
    # 1. Option A Fallback: Check bboxes.json
    bboxes_json_path = Path("tests/bboxes.json")
    if bboxes_json_path.exists():
        try:
            import json
            with bboxes_json_path.open("r") as f:
                bboxes_dict = json.load(f)
            if safe_filename in bboxes_dict:
                # bboxes.json has [x1, y1, x2, y2]
                detections = []
                for box in bboxes_dict[safe_filename]:
                    x1, y1, x2, y2 = box
                    detections.append(
                        SpineDetection(
                            bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                            confidence=None,
                            polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                        )
                    )
                analyze_log(f"[analyze_vision] Loaded {len(detections)} manual bboxes from tests/bboxes.json")
        except Exception as exc:
            analyze_log(f"[analyze_vision] Failed to load bboxes.json: {exc}")

    # 2. YOLO Detection (if no manual bboxes and YOLO is ready)
    if not detections:
        if detector_service.is_ready:
            try:
                detections = detector_service.detect_spines(str(temp_path))
                analyze_log(f"[analyze_vision] YOLO detected {len(detections)} spines")
            except Exception as exc:
                analyze_log(f"[analyze_vision] YOLO detection failed: {exc}")
        else:
            analyze_log("[analyze_vision] YOLO is not ready and no manual bboxes found. Fallback to 1 whole image bbox.")
            detections = [
                SpineDetection(
                    bbox=(0, 0, image_width, image_height),
                    confidence=None,
                    polygon=[[0, 0], [image_width, 0], [image_width, image_height], [0, image_height]],
                )
            ]

    detection_elapsed = time.perf_counter() - detection_started_at

    # 3. PaddleOCR for each BBox
    from worker.services.vision_service import vision_service
    ocr_results_payload = []
    crop_dir = upload_dir / "crops"
    
    ocr_started_at = time.perf_counter()
    for order, detection in enumerate(detections, start=1):
        crop_x, crop_y, crop_width, crop_height = detection.bbox
        crop_rect = (crop_x, crop_y, crop_width, crop_height)
        bbox_pixels = [float(crop_x), float(crop_y), float(crop_x + crop_width), float(crop_y + crop_height)]
        
        paddle_text = ""
        paddle_confidence = None
        call_number = ""
        crop_metadata = None

        try:
            spine_ocr_started_at = time.perf_counter()
            extracted, crop_metadata = vision_service.crop_and_ocr(
                str(temp_path),
                crop_rect=crop_rect,
                obb_polygon=detection.polygon if detection.is_obb else None,
                preprocess=preprocess,
                crop_output_path=str(crop_dir / f"{order:03d}.jpg"),
            )
            paddle_text = join_ocr_text(extracted)
            paddle_confidence = average_ocr_confidence(extracted)
            title, author, call_number = extract_ocr_fields(paddle_text)

            analyze_log(
                f"[analyze_vision] OCR spine={order} "
                f"text={paddle_text[:80]!r} elapsed={time.perf_counter() - spine_ocr_started_at:.1f}s"
            )
        except Exception as exc:
            analyze_log(f"[analyze_vision] OCR failed spine={order}: {exc}")
            title = None
            author = None

        ocr_results_payload.append(
            OCRResultItem(
                detected_order=order,
                raw_text=paddle_text,
                title=title,
                author=author,
                call_number=call_number or None,
                bbox=bbox_pixels,
                crop_image_path=crop_metadata.path if crop_metadata else None,
                ocr_confidence=paddle_confidence,
                detection_confidence=detection.confidence,
                obb_polygon=detection.polygon,
                crop_method=crop_metadata.method if crop_metadata else None,
                crop_size=crop_metadata.size if crop_metadata else None,
            )
        )

    ocr_elapsed = time.perf_counter() - ocr_started_at
    req = ScanSessionRequest(
        library_code=library_code,
        room_name=room_name,
        source_name=safe_filename,
        ocr_results=ocr_results_payload,
    )

    match_started_at = time.perf_counter()
    analyze_log(f"[analyze_vision] matching start items={len(ocr_results_payload)}")
    response = await process_scan_session_request(req, db, persist=False)
    analyze_log(f"[analyze_vision] matching done elapsed={time.perf_counter() - match_started_at:.1f}s")
    matching_elapsed = time.perf_counter() - match_started_at

    decision_counts: dict[str, int] = {}
    for result in response.results:
        decision_counts[result.decision] = decision_counts.get(result.decision, 0) + 1
        analyze_log(
            f"[analyze_vision] result spine={result.detected_order} "
            f"decision={result.decision} score={result.match_score or 0.0:.1f} "
            f"matched={result.matched_book!r} call_number={result.matched_call_number!r}"
        )
    analyze_log(f"[analyze_vision] decision summary={decision_counts}")
    try:
        artifact_prefix = await scan_artifact_service.save_scan(
            run_id=run_id,
            image_path=temp_path,
            library_code=library_code,
            room_name=room_name,
            response=response,
            timings={
                "detection": round(detection_elapsed, 4),
                "ocr": round(ocr_elapsed, 4),
                "matching": round(matching_elapsed, 4),
                "total_before_artifact_upload": round(time.perf_counter() - request_started_at, 4),
            },
            model_path=detector_service.model_path if detector_service.is_ready else None,
        )
        if artifact_prefix:
            response.artifact_run_id = run_id
            response.artifact_prefix = artifact_prefix
            analyze_log(f"[analyze_vision] artifacts saved prefix={artifact_prefix}")
    except Exception as exc:
        analyze_log(f"[analyze_vision] artifact save failed; continuing without S3: {exc}")
    return response


def bbox_to_pixels(bbox: list[float], image_width: int, image_height: int) -> list[float]:
    x1, y1, x2, y2 = bbox
    max_coord = max(abs(x1), abs(y1), abs(x2), abs(y2))

    if max_coord <= 1.0:
        # Some VLMs return normalized 0..1 coordinates even when prompted for 0..1000.
        x1, x2 = x1 * image_width, x2 * image_width
        y1, y2 = y1 * image_height, y2 * image_height
    elif max_coord <= 1000.0:
        x1, x2 = (x1 / 1000.0) * image_width, (x2 / 1000.0) * image_width
        y1, y2 = (y1 / 1000.0) * image_height, (y2 / 1000.0) * image_height

    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return [
        max(0.0, min(float(image_width), left)),
        max(0.0, min(float(image_height), top)),
        max(0.0, min(float(image_width), right)),
        max(0.0, min(float(image_height), bottom)),
    ]


def xyxy_to_xywh(bbox: list[float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    x = max(0, int(round(x1)))
    y = max(0, int(round(y1)))
    width = max(1, int(round(x2 - x1)))
    height = max(1, int(round(y2 - y1)))
    return x, y, width, height


def expand_short_spine_bbox(bbox: list[float], image_height: int) -> list[float]:
    x1, y1, x2, y2 = bbox
    height = y2 - y1
    if height < image_height * 0.25:
        return [x1, 0.0, x2, float(image_height)]
    return bbox


def join_ocr_text(extracted: list[dict]) -> str:
    return " ".join(str(item.get("text", "")).strip() for item in extracted if str(item.get("text", "")).strip())


def average_ocr_confidence(extracted: list[dict]) -> float | None:
    confidences = [float(item["confidence"]) for item in extracted if item.get("confidence") is not None]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)


def has_call_number_evidence(text: str | None) -> bool:
    return bool(text and re.search(r"\d{3}(?:[.,:]\d+)?", text))


def choose_call_number(vlm_call_number: str | None, ocr_text: str) -> str:
    if has_call_number_evidence(vlm_call_number):
        return vlm_call_number or ""
    if has_call_number_evidence(ocr_text):
        return ocr_text
    return vlm_call_number or ocr_text


def dedupe_text_parts(*parts: str) -> str:
    seen: set[str] = set()
    values: list[str] = []
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        values.append(normalized)
        seen.add(normalized)
    return " ".join(values)


def should_run_paddle_fallback(spine_order: int, vlm_call_number: str | None) -> bool:
    if has_call_number_evidence(vlm_call_number):
        return False

    max_fallback_spines = int(os.getenv("PADDLE_FALLBACK_MAX_SPINES", "0"))
    return spine_order <= max_fallback_spines


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
        started_at = time.perf_counter()
        analyze_log(f"[analyze_vlm] VLM start file={safe_filename} size={image_width}x{image_height}")
        vlm_result = await analyze_shelf_image_with_vlm(temp_path)
        analyze_log(f"[analyze_vlm] VLM done spines={len(vlm_result.spines)} elapsed={time.perf_counter() - started_at:.1f}s")
    except VLMServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"VLM analysis failed: {exc}") from exc

    ocr_results_payload = []

    for spine in vlm_result.spines:
        bbox = bbox_to_pixels(spine.bbox, image_width, image_height)
        bbox = expand_short_spine_bbox(bbox, image_height)
        crop_x, _, crop_width, _ = xyxy_to_xywh(bbox)
        crop_rect = (crop_x, 0, crop_width, image_height)
        paddle_text = ""
        paddle_confidence = None
        analyze_log(
            f"[analyze_vlm] VLM spine={spine.order} "
            f"call_number={spine.call_number!r} raw_text={(spine.raw_text or '')[:80]!r} bbox={spine.bbox}"
        )

        if should_run_paddle_fallback(spine.order, spine.call_number):
            try:
                from worker.services.vision_service import vision_service

                ocr_started_at = time.perf_counter()
                extracted = vision_service.manual_crop_and_ocr(
                    str(temp_path),
                    crop_rect,
                    preprocess=True,
                )
                paddle_text = join_ocr_text(extracted)
                paddle_confidence = average_ocr_confidence(extracted)
                analyze_log(
                    f"[analyze_vlm] Paddle fallback spine={spine.order} "
                    f"text={paddle_text[:80]!r} elapsed={time.perf_counter() - ocr_started_at:.1f}s"
                )
            except Exception as exc:
                analyze_log(f"[analyze_vlm] PaddleOCR fallback failed spine={spine.order}: {exc}")

        raw_text = dedupe_text_parts(spine.raw_text or "", paddle_text)
        call_number = choose_call_number(spine.call_number, paddle_text)

        ocr_results_payload.append(
            OCRResultItem(
                detected_order=spine.order,
                raw_text=raw_text,
                title=spine.title,
                author=spine.author,
                call_number=call_number,
                bbox=bbox,
                crop_image_path=None,
                ocr_confidence=paddle_confidence if paddle_confidence is not None else spine.confidence,
            )
        )

    req = ScanSessionRequest(
        library_code=library_code,
        room_name=room_name,
        source_name=safe_filename,
        ocr_results=ocr_results_payload,
    )

    match_started_at = time.perf_counter()
    analyze_log(f"[analyze_vlm] matching start items={len(ocr_results_payload)}")
    response = await process_scan_session_request(req, db, persist=False)
    analyze_log(f"[analyze_vlm] matching done elapsed={time.perf_counter() - match_started_at:.1f}s")
    return response


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
