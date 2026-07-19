from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameQuality:
    frame_index: int
    timestamp_seconds: float
    path: Path
    width: int
    height: int
    sharpness: float
    brightness: float
    contrast: float
    quality_score: float


def score_frame(frame: np.ndarray) -> tuple[float, float, float, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_brightness = float(gray.mean())
    contrast_deviation = float(gray.std())

    sharpness = min(1.0, math.log1p(laplacian_variance) / math.log1p(1200.0))
    brightness = max(0.0, 1.0 - abs(mean_brightness - 135.0) / 135.0)
    contrast = min(1.0, contrast_deviation / 64.0)
    quality_score = 0.6 * sharpness + 0.25 * brightness + 0.15 * contrast
    return sharpness, brightness, contrast, quality_score


def extract_quality_frames(
    video_path: Path,
    output_dir: Path,
    *,
    interval_seconds: float = 1.0,
    max_duration_seconds: float = 30.0,
    max_candidates: int = 60,
) -> tuple[list[FrameQuality], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("동영상 파일을 열 수 없습니다.")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if frame_count > 0 else 0.0
    if duration > max_duration_seconds:
        capture.release()
        raise ValueError(f"동영상은 {max_duration_seconds:.0f}초 이하여야 합니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    sample_every = max(1, round(fps * interval_seconds))
    candidates: list[FrameQuality] = []
    frame_index = 0

    try:
        while len(candidates) < max_candidates:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index / fps > max_duration_seconds:
                break
            if frame_index % sample_every != 0:
                frame_index += 1
                continue

            height, width = frame.shape[:2]
            sharpness, brightness, contrast, quality_score = score_frame(frame)
            frame_path = output_dir / f"frame-{frame_index:06d}.jpg"
            if not cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
                raise ValueError("추출 프레임을 저장하지 못했습니다.")
            candidates.append(
                FrameQuality(
                    frame_index=frame_index,
                    timestamp_seconds=frame_index / fps,
                    path=frame_path,
                    width=width,
                    height=height,
                    sharpness=sharpness,
                    brightness=brightness,
                    contrast=contrast,
                    quality_score=quality_score,
                )
            )
            frame_index += 1
    finally:
        capture.release()

    if not candidates:
        raise ValueError("동영상에서 분석 가능한 프레임을 추출하지 못했습니다.")
    return candidates, duration


video_frame_service = extract_quality_frames
