# OMR 다운스케일 작업 README

## 개요

이 브랜치는 OMR 인식 속도 개선을 위해, 인쇄용 고해상도 템플릿을 그대로 유지하면서도 인식 파이프라인에서는 저해상도 경로를 사용할 수 있도록 실험하는 작업 브랜치입니다.

핵심 목표는 다음과 같습니다.

- 인쇄 품질은 유지
- 인식용 처리 해상도는 낮춰서 전체 처리 비용 감소
- 특히 warp 이후의 binarization / morphology / ROI reading 비용 감소
- 정확도 저하 없이 속도 개선 가능한지 dev 환경에서 검증

## 현재 판단

이번 작업에서 가장 중요한 전제는 다음과 같습니다.

- 현재 코드의 `RoMaV2` 정렬은 내부 고정 해상도 프로파일의 영향을 크게 받을 수 있음
- 따라서 원본 템플릿 이미지를 줄인다고 해서 alignment 자체가 극적으로 빨라진다고 보장할 수는 없음
- 대신 실제로 줄일 수 있는 비용은 아래와 같음
  - warped image 기반 후처리
  - `_binarize_document()`
  - morphology
  - area ROI crop / mark reading
  - 일부 template decode / cache 비용

즉 이번 작업은 “템플릿 매칭 자체를 획기적으로 줄이는 작업”이라기보다, “정렬 이후의 downstream OMR processing을 가볍게 만드는 작업”으로 보는 것이 맞습니다.

## 구현 방향

현재 기본 구현 방향은 `Strategy A: align low, read low` 입니다.

의미:

- template / scan 이미지를 recognition용 해상도로 축소
- 축소된 이미지 기준으로 alignment 수행
- low-resolution warped image를 그대로 후속 처리에 사용
- ROI 좌표도 동일한 recognition scale로 축소해서 읽음

이 방향을 먼저 택한 이유:

- 실제 속도 절감 효과가 가장 직접적임
- ROI 좌표 체계가 단순 uniform scale로 맞아떨어짐
- 불필요하게 matcher 구조를 먼저 복잡하게 만들지 않아도 됨

## 현재 코드에 반영된 내용

### 1. recognition 파라미터 추가

파일:

- `worker/types.py`

추가된 주요 파라미터:

- `recognition_max_width`
- `reference_template_width`
- `adaptive_kernel_scaling`
- `morph_close_first`
- `min_morph_kernel_size`
- `morph_open_ksize`
- `morph_close_ksize`

의도:

- recognition용 목표 해상도 명시
- morphology kernel scaling 기준 명시
- morphology 순서 제어 가능하게 함

### 2. recognition resize helper 추가

파일:

- `worker/processors/v1.py`

추가된 주요 helper:

- `_resize_for_recognition()`
- `_scale_position()`
- `_scale_length()`
- `_scaled_kernel_size()`

의도:

- 인식용 해상도로 image를 축소
- ROI 좌표를 동일한 scale로 보정
- morphology kernel을 현재 working width 기준으로 자동 조정

### 3. low-resolution recognition path 추가

파일:

- `worker/processors/v1.py`

현재 반영된 흐름:

1. template 이미지 로드
2. template / scan을 recognition width 기준으로 축소
3. 축소된 이미지로 alignment 수행
4. low-resolution warped image로 binarization 수행
5. scaled ROI 좌표로 child area reading 수행

### 4. adaptive morphology 적용

파일:

- `worker/processors/v1.py`

반영 내용:

- `morph_close_ksize`, `morph_open_ksize`를 현재 recognition width 기준으로 스케일링
- `morph_close_first=True` 이면 `CLOSE -> OPEN`
- 아니면 `OPEN -> CLOSE`

의도:

- low-resolution에서도 kernel이 과대/과소 적용되지 않게 함
- dark filled mark 내부 hole 문제를 줄이는 방향으로 실험 가능하게 함

## 아직 남아 있는 것

이번 브랜치는 “완성본”이 아니라 “baseline implementation + dev 검증 준비” 상태입니다.

아직 남아 있는 핵심 작업:

- 실제 샘플 기준 recognition width 튜닝
- morphology 파라미터 튜닝
- before / after 성능 비교
- 정확도 비교
- 필요 시 matcher / precision 추가 최적화 검토

즉 지금 상태만으로 “최종 최적값이 확정됐다”는 뜻은 아닙니다.

## 검증 시 가장 먼저 볼 것

백오피스 job detail 로그 기준으로 아래 항목을 먼저 비교합니다.

- `TOTAL`
- `alignment`
- `binarization`
- `area_processing`

예상:

- `alignment`는 큰 폭으로 안 줄 수도 있음
- `binarization`은 줄어야 함
- `area_processing`도 줄 가능성 있음
- `TOTAL`은 upload / save / annotate 비중에 따라 생각보다 덜 줄 수도 있음

즉 “속도 개선이 있었는지”는 `TOTAL`만 보지 말고 stage별로 같이 봐야 합니다.

## 정확도 리스크

다음 리스크는 여전히 존재합니다.

- faint mark 손실
- morphology 과보정
- ROI scaling 오차
- identifier regression
- 템플릿별 민감도 차이

따라서 머지 후 dev 검증에서는 속도뿐 아니라 반드시:

- student ID 결과
- 답안 인식 결과
- threshold image
- area image
- false positive / false negative

를 같이 확인해야 합니다.

## 관련 문서

이 브랜치에는 아래 문서들이 함께 있습니다.

- `docs/omr_recognition_downscale_handoff_en.md`
- `docs/omr_downscale_before_after_eval_template_en.md`
- `docs/omr_downscale_team_review_checklist_en.md`
- `docs/omr_downscale_risks_and_safeguards_en.md`

역할:

- handoff / 설계 설명
- before / after 평가표
- 팀 리뷰 체크리스트
- 리스크 / 안전장치 / fallback 기준

## 현재 결론

지금 구현은 “속도개선 실험을 dev에서 검증할 수 있는 baseline” 입니다.

즉 다음 순서는:

1. PR 생성
2. develop merge
3. dev 인스턴스 배포
4. 같은 scan batch로 before / after 비교
5. 결과에 따라 2차 튜닝

한 줄 요약:

이번 브랜치는 고해상도 인쇄 자산은 유지하면서, low-resolution recognition path를 도입해 downstream OMR 처리 속도를 줄일 수 있는지 검증하기 위한 작업 브랜치입니다.
