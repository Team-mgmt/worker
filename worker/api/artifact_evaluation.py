from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from PIL import Image

from worker.schemas.artifact_evaluation import (
    ArtifactRunDetail,
    ArtifactRunSummary,
    GroundTruthSaveRequest,
    GroundTruthSaveResponse,
)
from worker.services.detection_evaluation_service import calculate_detection_metrics, predictions_from_result
from worker.services.scan_artifact_service import scan_artifact_service


router = APIRouter(prefix="/inference/artifacts", tags=["Artifact evaluation"])


def validated_run_id(run_id: str) -> str:
    try:
        return str(UUID(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id must be a UUID.") from exc


async def load_run(run_id: str, library_code: str | None) -> tuple[str, dict]:
    if not scan_artifact_service.enabled:
        raise HTTPException(status_code=503, detail="Scan artifact storage is not enabled.")
    try:
        prefix = await scan_artifact_service.find_run_prefix(validated_run_id(run_id), library_code)
        result = await scan_artifact_service.get_json(f"{prefix}/result.json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return prefix, result or {}


@router.get("", response_model=list[ArtifactRunSummary])
async def list_artifact_runs(
    library_code: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    if not scan_artifact_service.enabled:
        raise HTTPException(status_code=503, detail="Scan artifact storage is not enabled.")
    return await scan_artifact_service.list_runs(library_code=library_code, limit=limit)


@router.get("/{run_id}", response_model=ArtifactRunDetail)
async def get_artifact_run(run_id: str, library_code: str | None = None):
    prefix, result = await load_run(run_id, library_code)
    original_key = result.get("artifacts", {}).get("original_key")
    if not original_key:
        raise HTTPException(status_code=422, detail="The artifact result has no original image key.")
    original, _ = await scan_artifact_service.get_bytes(original_key)
    with Image.open(BytesIO(original)) as image:
        image_width, image_height = image.size
    ground_truth = await scan_artifact_service.get_json(f"{prefix}/ground-truth.json", required=False)
    library_query = f"?library_code={quote(library_code)}" if library_code else ""
    return ArtifactRunDetail(
        run_id=validated_run_id(run_id),
        prefix=prefix,
        result=result,
        ground_truth=ground_truth,
        image_width=image_width,
        image_height=image_height,
        original_url=f"/inference/artifacts/{run_id}/original{library_query}",
    )


@router.get("/{run_id}/original")
async def get_artifact_original(run_id: str, library_code: str | None = None):
    _, result = await load_run(run_id, library_code)
    original_key = result.get("artifacts", {}).get("original_key")
    if not original_key:
        raise HTTPException(status_code=422, detail="The artifact result has no original image key.")
    body, content_type = await scan_artifact_service.get_bytes(original_key)
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "private, max-age=300"})


@router.put("/{run_id}/ground-truth", response_model=GroundTruthSaveResponse)
async def save_ground_truth(
    run_id: str,
    request: GroundTruthSaveRequest,
    library_code: str | None = None,
):
    prefix, result = await load_run(run_id, library_code)
    original_key = result.get("artifacts", {}).get("original_key")
    if not original_key:
        raise HTTPException(status_code=422, detail="The artifact result has no original image key.")
    original, _ = await scan_artifact_service.get_bytes(original_key)
    with Image.open(BytesIO(original)) as image:
        image_width, image_height = image.size

    annotations = [annotation.model_dump(mode="json", by_alias=True) for annotation in request.annotations]
    for annotation in annotations:
        for x, y in annotation["polygon"]:
            if not (0 <= x <= image_width and 0 <= y <= image_height):
                raise HTTPException(status_code=422, detail=f"Annotation {annotation['id']} is outside the image.")

    predictions = predictions_from_result(result)
    metrics = calculate_detection_metrics(predictions, [annotation["polygon"] for annotation in annotations])
    yolo_obb_lines = [
        "0 "
        + " ".join(
            f"{x / image_width:.6f} {y / image_height:.6f}"
            for x, y in annotation["polygon"]
        )
        for annotation in annotations
    ]
    payload = {
        "schema_version": "1.0",
        "run_id": validated_run_id(run_id),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewer": request.reviewer.strip() or "admin",
        "image": {
            "key": original_key,
            "width": image_width,
            "height": image_height,
        },
        "model": result.get("model"),
        "annotations": annotations,
        "metrics": metrics.model_dump(mode="json"),
        "training_export": {
            "format": "yolo-obb",
            "class_names": ["book_spine"],
            "label_lines": yolo_obb_lines,
        },
    }
    key = f"{prefix}/ground-truth.json"
    await scan_artifact_service.put_json(key, payload)
    return GroundTruthSaveResponse(key=key, metrics=metrics, ground_truth=payload)
