import cv2
import numpy as np

from worker.services.video_frame_service import score_frame


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
