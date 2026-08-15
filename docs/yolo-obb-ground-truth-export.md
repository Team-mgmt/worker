# GT를 YOLO OBB 학습 데이터로 내보내기

백오피스에서 교정하고 저장한 `ground-truth.json`과 원본 이미지를 Ultralytics YOLO OBB
학습 구조로 변환한다. 이 도구는 학습을 실행하지 않으며 데이터만 내보낸다.

## 출력 구조

```text
dataset/
├── data.yaml
├── manifest.json
├── images/
│   └── train/<run_id>.jpg
└── labels/
    └── train/<run_id>.txt
```

라벨 한 줄은 책등 한 권이며 다음 형식이다. 좌표는 이미지 크기를 기준으로 0~1로
정규화된다.

```text
class_id x1 y1 x2 y2 x3 y3 x4 y4
```

현재 클래스는 `book_spine` 하나이므로 `class_id`는 항상 `0`이다.

## 단일 실행 내보내기

S3에서 같은 실행의 GT와 원본 이미지를 내려받은 뒤 실행한다.

```bash
./.venv313/bin/python -m worker.scripts.export_yolo_obb_dataset \
  --ground-truth /tmp/run/ground-truth.json \
  --image /tmp/run/original.png \
  --output ./datasets/book-spines-v2 \
  --split train
```

원본 파일이 `ground-truth.json` 옆에 `original.jpg`, `original.png` 등의 이름으로
있으면 `--image`를 생략할 수 있다.

## 아티팩트 폴더 일괄 내보내기

`ground-truth.json`과 `original.*`을 포함하도록 S3 아티팩트를 동기화한 경우 다음처럼
전체 실행을 변환한다.

```bash
./.venv313/bin/python -m worker.scripts.export_yolo_obb_dataset \
  --artifact-root ./outputs/ablation-artifacts \
  --output ./datasets/book-spines-v2 \
  --split train
```

학습·검증·테스트 분리는 서가 단위로 수행해야 한다. 같은 서가를 여러 각도에서 촬영한
이미지를 서로 다른 split에 섞으면 데이터 누수로 성능이 과대평가될 수 있다. 필요한
실행만 각각 `--split train`, `--split val`, `--split test`로 내보낸다.

## 검증과 안전장치

- GT polygon은 정확히 네 점이어야 한다.
- 모든 좌표가 이미지 경계 안에 있어야 한다.
- GT에 기록된 이미지 크기와 실제 원본 이미지 크기가 일치해야 한다.
- `manifest.json`에 원본 경로, 실행 ID, 이미지 크기, 라벨 개수를 기록한다.

한 권을 두 박스로 검출한 사례는 GT 편집기에서 한 권 전체를 감싸는 OBB 하나로 교정한
후 저장해야 한다. 예측 박스 두 개를 그대로 내보내면 분할 오류를 정답으로 학습하게 된다.
