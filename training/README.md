# Training

이 디렉터리는 버블 단위 `filled / not-filled` 이진 분류 모델 학습을 위한 준비 코드와 산출물을 둡니다.

현재 데이터 흐름은 다음과 같습니다.

1. worker가 버블 crop 이미지를 S3에 저장
2. Label Studio가 해당 이미지 경로를 task로 관리
3. 사람이 `filled` / `not-filled`를 라벨링
4. Label Studio export JSON에서
   - 이미지 경로
   - 최종 라벨
   - request/job/area 메타데이터
   를 추출해 학습용 manifest CSV로 변환

즉, export JSON은 이미지 자체가 아니라 `S3 이미지 경로와 라벨을 연결해 주는 인덱스` 역할을 합니다.

## 구조

```text
training/
  README.md
  manifests/
  src/
```

- `manifests/`
  - 학습용 CSV 산출물
- `src/`
  - export JSON -> manifest 변환 스크립트

## manifest 생성

예시:

```powershell
python training/src/export_labelstudio_dataset.py `
  --input project-2-at-2026-05-17-15-02-b24adaa3.json `
  --output training/manifests/project-2-problem.csv `
  --kind problem
```

생성되는 CSV는 최소한 아래 컬럼을 포함합니다.

- `image_uri`
- `label`
- `request_id`
- `job_id`
- `area_id`
- `local_id`
- `kind`
- `worker_verdict`
- `fill_ratio`
- `delta_fill_ratio`
- `baseline_fill_ratio`
- `template_uri`

초기 분류 모델은 `image_uri`가 가리키는 `scan crop`만 입력으로 사용하면 됩니다.
