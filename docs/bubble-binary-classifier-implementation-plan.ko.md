# 버블 이진 분류기 구현 계획

## 목표

OMR 처리 과정에서 추출한 버블 crop 이미지 1장을 입력으로 받아, 해당 버블이 실제로 마킹되었는지 여부를 `filled` / `not-filled`로 분류하는 이진 분류 모델을 구현한다.

초기 목표는 답안 버블(`kind=problem`)에 한정한 baseline 모델을 만드는 것이다.

## 현재 준비 상태

현재 다음 항목이 준비되어 있다.

- Label Studio export JSON 확보
- Label Studio export에서 `problem` 버블만 추출한 manifest CSV 생성
- JSON의 `data.scan` 경로와 사람 라벨(`filled` / `not-filled`) 매핑 확인
- S3 객체 실제 존재 확인
- 샘플 이미지 다운로드 및 버블 crop 확인
- 샘플 크기 분포 확인
  - 현재 확인된 `problem` 버블 crop은 `31x54` 고정 크기

관련 파일:

- export JSON: [project-2-at-2026-05-17-15-02-b24adaa3.json](/abs/path/C:/dev/QMR/project-2-at-2026-05-17-15-02-b24adaa3.json)
- 전체 manifest: [training/manifests/project-2-all.csv](/abs/path/C:/dev/QMR/training/manifests/project-2-all.csv)
- 답안 버블 manifest: [training/manifests/project-2-problem.csv](/abs/path/C:/dev/QMR/training/manifests/project-2-problem.csv)
- 변환 스크립트: [training/src/export_labelstudio_dataset.py](/abs/path/C:/dev/QMR/training/src/export_labelstudio_dataset.py)

## 문제 정의

샘플 단위는 버블 1개다.

- 입력: `scan` 버블 crop 이미지 1장
- 출력: `filled` 또는 `not-filled`

초기 단계에서는 `template` 이미지는 학습 입력으로 사용하지 않는다. 다만 manifest에는 함께 보관하여 이후 확장 가능성을 유지한다.

## 데이터셋 범위

1차 실험에서는 `kind=problem`만 사용한다.

이유:

- 답안 버블 분류가 현재 가장 중요한 목표다.
- `identifier`, `metadata`, `option`은 시각적 분포와 사용 목적이 다를 수 있다.
- 초기 baseline에서는 문제를 단순하게 유지하는 편이 해석과 비교에 유리하다.

후속 실험에서는 다음 두 방향을 비교할 수 있다.

- `problem` 전용 모델
- 모든 kind를 함께 학습한 모델

단, 후속 실험에서도 평가는 반드시 `problem` subset 성능을 별도로 기록해야 한다.

## 데이터셋 구성

현재 manifest는 다음 컬럼을 가진다.

- `image_uri`
- `template_uri`
- `label`
- `request_id`
- `job_id`
- `area_id`
- `area_index`
- `local_id`
- `kind`
- `worker_verdict`
- `fill_ratio`
- `delta_fill_ratio`
- `baseline_fill_ratio`

이 중 baseline 학습에 직접 필요한 최소 컬럼은 다음이다.

- `image_uri`
- `label`

나머지 컬럼은 추적과 오류 분석을 위해 유지한다.

## 데이터 split 전략

random row-level split은 사용하지 않는다.

같은 OMR 업로드에서 나온 버블들이 train/val/test에 동시에 섞이면 leakage가 발생할 수 있다.

따라서 split은 최소한 `request_id` 기준으로 수행한다.

권장 비율:

- train: 80%
- val: 10%
- test: 10%

split 결과물은 별도 manifest로 저장한다.

예:

- `training/manifests/project-2-problem-train.csv`
- `training/manifests/project-2-problem-val.csv`
- `training/manifests/project-2-problem-test.csv`

## 이미지 접근 전략

초기 baseline은 S3 이미지를 학습 전에 로컬 디렉터리로 다운로드하는 방식으로 진행한다.

이유:

- 구현이 단순하다.
- DataLoader에서 네트워크 I/O를 직접 다루지 않아도 된다.
- spot 인스턴스에서도 경로 추적과 재시작이 쉽다.

권장 방식:

- manifest는 S3 URI 기준으로 유지
- 학습 직전 별도 스크립트로 필요한 이미지들을 로컬 캐시 디렉터리에 다운로드
- 필요 시 `request_id/job_id` 구조를 보존해 저장

## 모델 전략

첫 실험에서는 두 모델을 각각 따로 학습하여 비교한다.

비교 대상:

1. `ResNet18`
2. `ConvNeXt-Tiny`

이 둘은 앙상블이 아니라, 동일 데이터셋과 동일 split으로 각각 독립 실험한다.

이유:

- `ResNet18`은 가볍고 안정적인 baseline이다.
- `ConvNeXt-Tiny`는 더 현대적인 CNN 백본이다.
- 둘을 비교해야 현재 문제에서 더 복잡한 모델이 실제로 의미가 있는지 판단할 수 있다.

## 모델 로딩 방식

모델은 AWS에서 제공하는 것이 아니라, 학습 코드 안에서 `torchvision`을 통해 불러온다.

예:

- `torchvision.models.resnet18`
- `torchvision.models.convnext_tiny`

pretrained ImageNet weight를 사용하고, 마지막 classification head만 2클래스로 교체한다.

## 입력 전처리

현재 버블 crop 크기는 `31x54`다.

CNN backbone 입력을 위해 resize가 필요하다.

초기 제안:

- grayscale 이미지를 로드
- 3채널로 복제하거나 RGB로 변환
- `224x224`로 resize
- 표준 normalize 적용

추가 전처리는 baseline 결과를 본 뒤 최소한으로만 늘린다.

## 학습 지표

accuracy만 사용하지 않는다.

우선 확인할 지표:

- precision
- recall
- F1

특히 `filled` 클래스의 recall을 중요하게 본다.

이유:

- 실제 마킹 버블을 놓치는 오류는 운영상 중요도가 높다.

## 임계값 전략

모델은 `filled` 확률을 출력하도록 구성한다.

초기 threshold는 `0.5`로 시작한다.

그 후 validation set에서 threshold sweep을 수행해 더 적절한 값을 선택할 수 있다.

threshold는 모델 weight와 분리된 설정값으로 관리한다.

## 구현 순서

1. `request_id` 기준 split 스크립트 작성
2. train/val/test manifest 생성
3. 로컬 이미지 캐시 스크립트 작성
4. PyTorch `Dataset` / `DataLoader` 구현
5. `ResNet18` baseline 학습 코드 구현
6. `ConvNeXt-Tiny` baseline 학습 코드 구현
7. validation/test 평가 코드 구현
8. 결과 비교 및 threshold 조정

## 실행 환경

실험은 Dev Spot GPU Instance를 사용한다.

접속 방식:

- SSM 접속

운영 원칙:

- checkpoint를 자주 저장
- manifest와 결과를 S3에 백업
- 긴 실험을 한 번에 몰아 돌리지 않음
- 재시작 가능하게 작업 단위를 작게 유지

## S3 백업 원칙

spot 회수 위험을 고려하여 다음 항목을 주기적으로 S3에 업로드한다.

- train/val/test manifest
- 학습 설정 파일
- checkpoint
- best model
- metric 요약
- prediction/evaluation 결과

## 후속 확장

baseline 이후 다음 항목을 검토할 수 있다.

- `problem` 외 kind 추가
- `template` 이미지 활용
- worker metric(`fill_ratio`, `delta_fill_ratio`)을 feature로 결합
- low-confidence case만 별도 재검수하는 보조 모델 운영
- 최종적으로 worker 추론 파이프라인에 통합

## 완료 기준

다음 조건을 만족하면 1차 구현 완료로 본다.

- `problem` 데이터셋 train/val/test split 완료
- `ResNet18` baseline 학습 가능
- `ConvNeXt-Tiny` baseline 학습 가능
- 두 모델의 val/test 성능 비교 가능
- S3 백업을 포함한 재현 가능한 학습 흐름 확보
