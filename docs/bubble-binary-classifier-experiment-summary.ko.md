# Bubble Binary Classifier 실험 정리

## 목적

- 목표: 버블 crop 이미지 1장을 보고 `filled / not-filled`를 판정하는 이진 분류 모델을 만드는 것
- 적용 대상: `kind=problem`인 답안 버블
- 최종 활용 방향:
  - 기존 OMR 규칙 기반 판정을 보조하거나
  - 애매한 버블만 모델이 재판정하는 방식으로 worker 파이프라인에 연계

## 데이터 준비

### 원본 데이터

- Label Studio export JSON
  - 파일: `project-2-at-2026-05-17-15-02-b24adaa3.json`
- 실제 버블 이미지
  - S3 경로 예시:
    - `s3://dev-hi4labs-label-studio/qmr-worker/debug/.../__scan.png`
    - 실제 다운로드는 권한 이슈로 `dev-qmr-assets` 버킷 기준으로 수행

### 학습용 manifest 생성

- 스크립트:
  - `training/src/export_labelstudio_dataset.py`
- 생성 파일:
  - `training/manifests/project-2-all.csv`
  - `training/manifests/project-2-problem.csv`

### 전체 라벨 분포

- 총 task 수: `10539`
- 라벨 분포:
  - `not-filled`: `9386`
  - `filled`: `1153`

### kind 분포

- `problem`: `4499`
- `metadata`: `3660`
- `identifier`: `2340`
- `option`: `40`

### 이번 실험에서 사용한 데이터

- `kind=problem`만 사용
- 이유:
  - 현재 목적이 답안 버블 판정이기 때문
  - `identifier`, `metadata`는 목적이 다름
  - 초기 baseline은 문제를 단순하게 유지하는 것이 유리함

## 전처리 및 split

### 왜 `request_id` 기준으로 split 했는가

같은 `request_id`는 같은 OMR 업로드 / 같은 스캔에서 나온 버블 묶음이다.

즉 같은 `request_id` 내부의 버블들은 보통 아래 특성을 공유한다.

- 같은 인쇄 상태
- 같은 왜곡
- 같은 정렬 결과
- 같은 노이즈/조명 특성

만약 행 단위 랜덤 split을 하면 같은 답안지에서 나온 매우 비슷한 버블이 `train`과 `test`에 동시에 들어갈 수 있다. 그러면 성능이 실제보다 더 좋아 보일 수 있다.

그래서 이번 실험은 **행 단위 랜덤 분할이 아니라 `request_id` 기준 group split**을 사용했다.

### split 스크립트

- `training/src/split_problem_dataset.py`

### split 결과

- 전체 `problem` 샘플 수: `4499`
- `request_id` 개수: `13`

분할 결과:

- train
  - rows: `3824`
  - request_ids: `10`
  - labels:
    - `not-filled`: `3146`
    - `filled`: `678`
- val
  - rows: `225`
  - request_ids: `1`
  - labels:
    - `not-filled`: `180`
    - `filled`: `45`
- test
  - rows: `450`
  - request_ids: `2`
  - labels:
    - `not-filled`: `405`
    - `filled`: `45`

### 주의점

- 현재 `request_id`가 `13개`뿐이라 validation / test 크기가 작다.
- 따라서 현재 점수는 baseline 비교용으로는 의미가 있지만, 운영 품질을 확정하기엔 데이터가 더 필요하다.

## 이미지 캐시

### 캐시 목적

- S3 원본 버블 이미지를 매번 다시 읽지 않기 위해 로컬 캐시 사용
- 이후 재현을 위해 캐시 자체도 S3에 저장

### 관련 스크립트

- `training/src/cache_problem_images.py`

### 실제 캐시 결과

- `__scan.png` 개수: `4499`
- 캐시 용량: 약 `19MB`

### 캐시 재사용용 S3 백업

- 코드 번들:
  - `s3://dev-qmr-assets/qmr-worker/training/training_bundle.zip`
- 이미지 캐시 번들:
  - `s3://dev-qmr-assets/qmr-worker/training/cache_bundle.tgz`

## 이미지 크기 확인

### 확인 스크립트

- `training/src/inspect_problem_image_sizes.py`

### 확인 결과

샘플 확인 결과, `problem` 버블 crop은 모두 동일한 크기를 가졌다.

- width: `31`
- height: `54`

즉 현재 실험에서 사용하는 버블 crop은 사실상 고정 크기이다.

## 딥러닝 학습 설정

### 공통

- 입력: `problem` 버블의 `scan` 이미지
- 클래스:
  - `filled`
  - `not-filled`
- 이미지 전처리:
  - resize to `224x224`
  - grayscale -> 3채널
  - normalize `[0.5, 0.5, 0.5]`

### 사용 모델

- `ResNet18`
- `ConvNeXt-Tiny`

### early stopping

추가 구현:

- `training/src/train.py`

지원 옵션:

- `--early-stopping-patience`
- `--early-stopping-min-delta`

현재 기준:

- `val_filled_f1`를 모니터링
- 일정 epoch 동안 성능 향상이 없으면 학습 중단
- 가장 좋았던 checkpoint는 `best.pt`로 보존

### 체크포인트 / 결과 저장

각 실험 경로에는 보통 아래 파일이 생성된다.

- `epoch-001.pt`, `epoch-002.pt`, ...
- `best.pt`
- `metrics.json`

S3 백업 옵션을 사용하면 epoch마다 S3에도 sync된다.

## 머신러닝 학습 설정

### 목적

데이터가 작고 기존 worker가 이미 강한 수치 feature를 계산하고 있으므로, 이미지 CNN 외에 classic ML도 비교했다.

### 사용 feature

- `fill_ratio`
- `delta_fill_ratio`
- `baseline_fill_ratio`
- `area_index`
- `worker_verdict`

### 사용 모델

- `Logistic Regression`
- `Random Forest`

### 관련 스크립트

- `training/src/train_tabular_ml.py`
- `training/scripts/run_logistic_regression.sh`
- `training/scripts/run_random_forest.sh`

## 성능 비교

### 1. ResNet18 + early stopping

- best epoch: `1`
- test metrics:
  - accuracy: `0.9956`
  - filled precision: `1.0000`
  - filled recall: `0.9556`
  - filled f1: `0.9773`

### 2. ResNet18 + full 20 epochs

- test metrics:
  - accuracy: `0.9911`
  - filled precision: `1.0000`
  - filled recall: `0.9111`
  - filled f1: `0.9535`

해석:

- 더 오래 학습했다고 더 좋아지지 않았다.
- 오히려 `filled recall`, `filled f1`가 내려갔다.
- 현재 데이터 크기에서는 full20보다 early stopping으로 고른 `best.pt`가 더 적절하다.

### 3. ConvNeXt-Tiny + early stopping

- best epoch: `1`
- test metrics:
  - accuracy: `0.9889`
  - filled precision: `1.0000`
  - filled recall: `0.8889`
  - filled f1: `0.9412`

### 4. ConvNeXt-Tiny + full 20

- full20은 중간 checkpoint와 `best.pt`는 저장되었으나, 실행을 중간 중단해서 최종 `metrics.json`은 확정하지 않았다.
- 다만 early stopping 결과와 중간 로그 흐름상, ResNet18을 뒤집을 가능성은 높지 않았다.

### 5. Logistic Regression

- val metrics:
  - accuracy: `1.0000`
  - filled precision: `1.0000`
  - filled recall: `1.0000`
  - filled f1: `1.0000`
- test metrics:
  - accuracy: `0.9933`
  - filled precision: `1.0000`
  - filled recall: `0.9333`
  - filled f1: `0.9655`

### 6. Random Forest

- val metrics:
  - accuracy: `1.0000`
  - filled precision: `1.0000`
  - filled recall: `1.0000`
  - filled f1: `1.0000`
- test metrics:
  - accuracy: `0.9911`
  - filled precision: `1.0000`
  - filled recall: `0.9111`
  - filled f1: `0.9535`

## 최종 비교 요약

현재까지의 순위:

1. `ResNet18 + early stopping`
2. `Logistic Regression`
3. `Random Forest`
4. `ConvNeXt-Tiny + early stopping`

해석:

- 최고 성능은 `ResNet18`
- 하지만 `Logistic Regression`도 상당히 강했다
- 즉 이 문제는 딥러닝만 가능한 문제가 아니라, 기존 수치 feature 기반 ML도 충분히 경쟁력이 있다

## 현재 판단

### 1차 최종 후보

- 이미지 기반:
  - `ResNet18 best.pt`
- 수치 feature 기반:
  - `logistic_regression model.pkl`

### 추천 활용 방식

초기 운영 연결은 아래 둘 중 하나가 적절하다.

1. 기존 규칙 기반 유지 + 애매한 버블만 모델 재판정
2. shadow mode로 모델 예측을 같이 남기고 기존 방식과 비교

바로 규칙 기반 전체를 대체하기보다, 애매한 버블 보조 판정기로 붙이는 것이 안전하다.

## 한계

- `request_id`가 `13개`뿐이라 split 규모가 작음
- validation/test가 작아 현재 점수가 다소 낙관적일 수 있음
- 더 많은 `request_id` 확보 후 재실험 필요
- 현재는 `problem`만 사용했으며, 다른 kind는 별도 목적임

## 추후 구현 방향

worker 연계 시 필요한 작업:

- 모델 파일 로드
  - `best.pt` 또는 `model.pkl`
- 추론 함수 구현
  - 이미지 기반 또는 수치 feature 기반
- threshold 설정
- 기존 규칙 기반과의 결합 방식 정의
  - 완전 대체
  - 애매한 버블만 재판정
  - shadow mode

## 학습 방법 / 실행 코드

### 1. training 번들 업로드

로컬 PowerShell:

```powershell
cd C:\dev\QMR
Compress-Archive -Path .\training -DestinationPath .\training_bundle.zip -Force
aws s3 cp .\training_bundle.zip s3://dev-qmr-assets/qmr-worker/training/training_bundle.zip --profile work-sso
```

### 2. 인스턴스에서 번들 다운로드

```bash
mkdir -p ~/qmr-train
cd ~/qmr-train
aws s3 cp s3://dev-qmr-assets/qmr-worker/training/training_bundle.zip .
unzip -o training_bundle.zip
```

### 3. split 생성

```bash
/opt/qmr-worker/.venv/bin/python training/src/split_problem_dataset.py \
  --input training/manifests/project-2-problem.csv \
  --output-dir training/manifests/splits
```

### 4. 이미지 캐시 생성

```bash
/opt/qmr-worker/.venv/bin/python training/src/cache_problem_images.py \
  --manifest training/manifests/splits/project-2-problem-train.csv \
  --manifest training/manifests/splits/project-2-problem-val.csv \
  --manifest training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --bucket-override dev-hi4labs-label-studio=dev-qmr-assets
```

### 5. 캐시 재사용용 백업

```bash
cd ~/qmr-train
tar -czf cache_bundle.tgz training/cache
aws s3 cp cache_bundle.tgz s3://dev-qmr-assets/qmr-worker/training/cache_bundle.tgz
```

### 6. symlink 생성

```bash
cd ~/qmr-train/training/cache
rm -rf dev-hi4labs-label-studio
ln -s dev-qmr-assets dev-hi4labs-label-studio
cd ~/qmr-train
```

### 7. ResNet18 early stopping 실행

```bash
sh training/scripts/run_resnet18_es20_pat3.sh
```

### 8. ResNet18 full20 실행

```bash
sh training/scripts/run_resnet18_full20.sh
```

### 9. ConvNeXt-Tiny early stopping 실행

```bash
sh training/scripts/run_convnext_tiny_es20_pat3.sh
```

### 10. ConvNeXt-Tiny full20 실행

```bash
sh training/scripts/run_convnext_tiny_full20.sh
```

### 11. CPU 기반 Logistic Regression 실행

```bash
./ml-venv/bin/python training/src/train_tabular_ml.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --output-dir training/runs/logistic_regression \
  --model logistic_regression \
  --s3-backup-uri s3://dev-qmr-assets/qmr-worker/training/runs/logistic_regression
```

또는:

```bash
sh training/scripts/run_logistic_regression.sh
```

### 12. CPU 기반 Random Forest 실행

```bash
./ml-venv/bin/python training/src/train_tabular_ml.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --output-dir training/runs/random_forest \
  --model random_forest \
  --s3-backup-uri s3://dev-qmr-assets/qmr-worker/training/runs/random_forest
```

또는:

```bash
sh training/scripts/run_random_forest.sh
```

## 산출물 위치

예시:

- ResNet18
  - `s3://dev-qmr-assets/qmr-worker/training/runs/resnet18/`
- Logistic Regression
  - `s3://dev-qmr-assets/qmr-worker/training/runs/logistic_regression/`

주요 파일:

- 딥러닝:
  - `best.pt`
  - `epoch-XXX.pt`
  - `metrics.json`
- 머신러닝:
  - `model.pkl`
  - `metrics.json`
