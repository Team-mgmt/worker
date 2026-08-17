from io import BytesIO

from PIL import Image

from worker.services.detection_confidence_visualization_service import render_confidence_visualization


def test_confidence_visualization_focuses_overlapping_candidates() -> None:
    source = BytesIO()
    Image.new("RGB", (400, 300), "white").save(source, format="JPEG")
    result = {
        "inference": {
            "results": [
                {
                    "detected_order": 19,
                    "detection_confidence": 0.56,
                    "obb_polygon": [[100, 40], [180, 40], [180, 260], [100, 260]],
                },
                {
                    "detected_order": 20,
                    "detection_confidence": 0.795,
                    "obb_polygon": [[120, 30], [240, 30], [240, 270], [120, 270]],
                },
                {
                    "detected_order": 21,
                    "detection_confidence": 0.556,
                    "obb_polygon": [[190, 40], [250, 40], [250, 260], [190, 260]],
                },
                {
                    "detected_order": 30,
                    "detection_confidence": 0.9,
                    "obb_polygon": [[300, 40], [340, 40], [340, 260], [300, 260]],
                },
            ]
        }
    }

    rendered = render_confidence_visualization(
        source.getvalue(),
        result,
        threshold=0.6,
        focus_order=20,
    )

    with Image.open(BytesIO(rendered)) as image:
        assert image.width < 400
        assert image.height == 300
