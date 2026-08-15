from pathlib import Path

import cv2
import numpy as np

from worker.services.video_frame_service import (
    FrameQuality,
    score_frame,
    select_target_search_frames,
)


def test_sharp_frame_scores_higher_than_blurred_frame() -> None:
    checkerboard = np.zeros((240, 320, 3), dtype=np.uint8)
    for y in range(0, 240, 20):
        for x in range(0, 320, 20):
            if (x // 20 + y // 20) % 2 == 0:
                checkerboard[y : y + 20, x : x + 20] = 255

    blurred = cv2.GaussianBlur(checkerboard, (31, 31), 0)
    sharp_metrics = score_frame(checkerboard)
    blurred_metrics = score_frame(blurred)

    assert sharp_metrics[0] > blurred_metrics[0]
    assert sharp_metrics[3] > blurred_metrics[3]


def test_mid_brightness_scores_higher_than_dark_frame() -> None:
    mid = np.full((120, 120, 3), 135, dtype=np.uint8)
    dark = np.zeros((120, 120, 3), dtype=np.uint8)

    assert score_frame(mid)[1] > score_frame(dark)[1]


def _frame(index: int, timestamp: float, quality: float) -> FrameQuality:
    return FrameQuality(
        frame_index=index,
        timestamp_seconds=timestamp,
        path=Path(f"frame-{index}.jpg"),
        width=1920,
        height=1080,
        sharpness=quality,
        brightness=1.0,
        contrast=1.0,
        quality_score=quality,
    )


def test_target_search_frames_are_high_quality_and_temporally_diverse() -> None:
    candidates = [
        _frame(0, 0.0, 0.80),
        _frame(1, 0.5, 0.99),
        _frame(2, 1.0, 0.98),
        _frame(3, 2.0, 0.90),
        _frame(4, 3.0, 0.85),
    ]

    selected = select_target_search_frames(candidates, limit=3, minimum_spacing_seconds=1.0)

    assert [frame.frame_index for frame in selected] == [1, 3, 4]
    assert [frame.timestamp_seconds for frame in selected] == sorted(
        frame.timestamp_seconds for frame in selected
    )


def test_target_search_frame_selection_fills_limit_for_short_video() -> None:
    candidates = [_frame(0, 0.0, 0.8), _frame(1, 0.2, 0.7)]

    selected = select_target_search_frames(candidates, limit=3, minimum_spacing_seconds=1.0)

    assert [frame.frame_index for frame in selected] == [0, 1]
