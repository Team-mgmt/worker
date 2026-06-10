# 버블 이진 분류기 실행 런북

이 문서는 현재 로컬 워크스페이스에서 준비한 `training/` 코드를 Dev Spot GPU Instance에서 실제로 실행하는 절차를 정리한다.

## 전제

- 로컬 워크스페이스에 `training/` 폴더와 manifest CSV가 준비되어 있다.
- AWS CLI `work-sso` 프로필이 로컬에서 동작한다.
- EC2 `dev-qmr-worker-auto`에 Session Manager로 접속 가능하다.
- 인스턴스 내부 Python은 `/opt/qmr-worker/.venv/bin/python`을 사용한다.

## 로컬에서 할 일

### 1. training 폴더 압축

PowerShell:

```powershell
Compress-Archive -Path .\training -DestinationPath .\training_bundle.zip -Force
```

### 2. S3 업로드

```powershell
aws s3 cp .\training_bundle.zip s3://dev-qmr-assets/qmr-worker/training/training_bundle.zip --profile work-sso
```

필요하면 export JSON도 함께 업로드:

```powershell
aws s3 cp .\project-2-at-2026-05-17-15-02-b24adaa3.json s3://dev-qmr-assets/qmr-worker/training/project-2-at-2026-05-17-15-02-b24adaa3.json --profile work-sso
```

## 인스턴스에서 할 일

### 1. 작업 디렉터리 생성

```bash
mkdir -p ~/qmr-train
cd ~/qmr-train
```

### 2. 번들 다운로드 및 압축 해제

```bash
aws s3 cp s3://dev-qmr-assets/qmr-worker/training/training_bundle.zip .
unzip -o training_bundle.zip
ls
ls training
```

### 3. 실행 환경 확인

```bash
nvidia-smi
/opt/qmr-worker/.venv/bin/python --version
/opt/qmr-worker/.venv/bin/python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
aws sts get-caller-identity
```

## 데이터 split

로컬에서 이미 split을 만들어뒀더라도 인스턴스에서 다시 재현 가능하게 한 번 더 실행하는 편이 안전하다.

```bash
cd ~/qmr-train
/opt/qmr-worker/.venv/bin/python training/src/split_problem_dataset.py \
  --input training/manifests/project-2-problem.csv \
  --output-dir training/manifests/splits
```

## 이미지 캐시

train/val/test를 한 번에 캐시:

```bash
/opt/qmr-worker/.venv/bin/python training/src/cache_problem_images.py \
  --manifest training/manifests/splits/project-2-problem-train.csv \
  --manifest training/manifests/splits/project-2-problem-val.csv \
  --manifest training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache
```

필요 시 template도 함께 캐시:

```bash
/opt/qmr-worker/.venv/bin/python training/src/cache_problem_images.py \
  --manifest training/manifests/splits/project-2-problem-train.csv \
  --manifest training/manifests/splits/project-2-problem-val.csv \
  --manifest training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --include-template
```

## 학습 실행

현재 인스턴스는 worker가 GPU 메모리를 일부 점유하고 있으므로, 초기 배치 크기는 보수적으로 시작한다.

### ResNet18

```bash
/opt/qmr-worker/.venv/bin/python training/src/train.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --output-dir training/runs/resnet18 \
  --model resnet18 \
  --epochs 5 \
  --batch-size 32 \
  --num-workers 2
```

### ConvNeXt-Tiny

```bash
/opt/qmr-worker/.venv/bin/python training/src/train.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --output-dir training/runs/convnext_tiny \
  --model convnext_tiny \
  --epochs 5 \
  --batch-size 16 \
  --num-workers 2
```

## 결과 확인

각 실행 결과는 다음에 저장된다.

- `training/runs/resnet18/metrics.json`
- `training/runs/convnext_tiny/metrics.json`
- `training/runs/.../best.pt`
- `training/runs/.../epoch-*.pt`

비교할 지표:

- `accuracy`
- `filled_precision`
- `filled_recall`
- `filled_f1`

## S3 백업

spot 인스턴스이므로 결과를 S3에 자주 올리는 것이 중요하다.

수동 백업 예:

```bash
aws s3 cp training/runs s3://dev-qmr-assets/qmr-worker/training/runs --recursive
```

또는 `train.py` 실행 시 `--s3-backup-uri`를 넣어서 epoch마다 sync하게 할 수 있다.

예:

```bash
/opt/qmr-worker/.venv/bin/python training/src/train.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --output-dir training/runs/resnet18 \
  --model resnet18 \
  --epochs 5 \
  --batch-size 32 \
  --num-workers 2 \
  --s3-backup-uri s3://dev-qmr-assets/qmr-worker/training/runs/resnet18
```

## 문제 발생 시 우선 확인

### GPU 메모리 부족

- batch size 줄이기
- `num_workers` 줄이기
- 우선 `ResNet18`부터 실행

### 이미지 파일 누락

- `training/cache/...` 경로 확인
- `cache_problem_images.py` 다시 실행

### worker와 자원 충돌

- `nvidia-smi`로 현재 GPU 메모리 확인
- 부하 적은 시간대에 실행
- epoch 수를 줄여 짧게 돌리기

## 현재 구현 범위

현재 코드로 가능한 범위:

- Label Studio export -> manifest
- `request_id` 기준 split
- 로컬 이미지 캐시
- `ResNet18` 학습
- `ConvNeXt-Tiny` 학습
- val/test 평가

후속으로 추가 가능한 범위:

- threshold sweep
- kind별 추가 실험
- template 활용
- worker metric 결합
