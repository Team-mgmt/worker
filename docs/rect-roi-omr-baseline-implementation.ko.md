# Rect ROI OMR Baseline 구현 정리

## 개요

이번 변경은 OMR 버블 판독에 **직사각형 ROI 기반 측정 방식**을 추가한 구현입니다.

대상은 좌우 버블 테두리를 제거한 새로운 답안지 템플릿(`new_template`)이며, 기존 방식에서 좌우 테두리의 검은 영역까지 fill ratio 계산에 포함되어 발생하던 false positive를 줄이는 것이 목적입니다.

기존 타원형(`ellipse`) 측정 방식은 fallback으로 유지하고, 이번 구현에서는 다음을 추가했습니다.

- 직사각형 ROI 측정
- baseline `+10%` 보정
- ROI 전용 morphology 실험 옵션
- raw baseline / adjusted baseline 분리 기록

## 문제 정의

기존 OMR FP의 주요 원인은 단순히 버블 내부 숫자만이 아니라, **좌우 테두리까지 검은 영역 계산에 포함되는 점**이었습니다.

이 문제는 특히 아래 상황에서 더 크게 드러났습니다.

- 템플릿이 SVG에서 raster 이미지로 렌더링될 때
- 렌더링 후 선이 SVG 원본보다 더 두껍게 보일 때
- 미마킹 버블도 실제 사진/처리 결과에서는 채움 비율이 높게 나올 때

즉 SVG 기준으로는 낮은 baseline이어야 하는 버블이, 실제 처리 이미지에서는 더 “뚱뚱하게” 보여 오검출이 발생하는 문제가 있었습니다.

## 구현 목표

이번 구현의 목표는 다음과 같습니다.

- 좌우 테두리 영향 줄이기
- 실제 마킹과 더 관련 있는 내부 영역만 읽기
- 템플릿 baseline 비교 로직은 유지하기
- 기존 ellipse 방식은 비교/복구용으로 남겨두기

## 동작 방식 변화

### 기존 흐름

1. 백오피스에서 버블 bbox 좌표를 저장
2. worker가 그 bbox 안에 타원 mask를 씌워 fill ratio 측정
3. 템플릿 baseline과 학생 답안 fill ratio를 같은 ellipse 기반으로 비교

### 변경 후 흐름

1. 백오피스는 동일하게 버블 bbox 좌표를 저장
2. worker는 필요 시 ellipse 대신 직사각형 ROI로 fill ratio 측정
3. 템플릿 baseline도 같은 rect ROI 기준으로 계산
4. baseline에 `+10%` 오프셋을 더한 뒤 delta 계산
5. 필요하면 ROI 내부 morphology를 적용한 후 측정

## 주요 변경 사항

### 1. 새 측정 shape 추가

버블 측정 shape를 아래 두 가지로 확장했습니다.

- `ellipse`
- `rect`

`ellipse`는 기존 방식이고, `rect`는 새 템플릿에 맞춘 새 방식입니다.

### 2. 직사각형 ROI 측정 추가

`rect` 모드에서는 더 이상 버블 측정을 위해 타원 mask를 씌우지 않습니다.

대신 버블 bbox 내부를 직사각형 ROI로 보고 그 영역의 검은 비율을 계산합니다.

새 템플릿은 좌우 테두리가 제거되어 실제 유효 마킹 영역이 닫힌 타원보다는 직사각형 중심 영역에 더 가깝기 때문에, 이 구조에 더 잘 맞습니다.

### 3. baseline `+10%` 보정

다음 파라미터를 추가했습니다.

- `baseline_fill_ratio_offset = 0.10`

판정 시 baseline은 다음처럼 사용됩니다.

```text
adjusted_baseline_fill_ratio = baseline_fill_ratio + baseline_fill_ratio_offset
```

최종 delta는:

```text
delta_fill_ratio = fill_ratio - adjusted_baseline_fill_ratio
```

이 보정은 SVG가 raster/bitmap 형태로 처리되면서 선이 더 두꺼워 보이는 현상을 baseline 단계에서 흡수하려는 목적입니다.

### 4. raw baseline / adjusted baseline 분리

이제 baseline 관련 값은 명시적으로 두 단계로 기록됩니다.

- `baseline_fill_ratio`
  - 템플릿에서 실제 측정한 raw baseline
- `adjusted_baseline_fill_ratio`
  - raw baseline에 offset을 더한 실제 판정용 baseline

이렇게 분리해두면 디버깅 시

- 템플릿 원래 baseline이 얼마였는지
- 최종 판정에 어떤 baseline이 쓰였는지

를 혼동 없이 확인할 수 있습니다.

### 5. ROI 전용 morphology 옵션 추가

ROI 내부 후처리 실험을 위해 다음 파라미터를 추가했습니다.

- `bubble_roi_use_morphology`
- `bubble_roi_morph_close_first`
- `bubble_roi_morph_open_ksize`
- `bubble_roi_morph_close_ksize`

이 값들은 문서 전체 threshold morphology 설정과 분리되어 있습니다.

즉 ROI 실험 설정이 문서 전체 morphology 옵션에 종속되지 않도록 독립 파라미터로 설계했습니다.

기본값은 off입니다.

## 파일별 변경 사항

### `worker/types.py`

추가/수정:

- `BubbleShape = Literal["ellipse", "rect"]`
- `baseline_fill_ratio_offset`
- `bubble_measurement_shape`
- ROI morphology 관련 파라미터
- `AreaMetrics.adjusted_baseline_fill_ratio`

### `worker/processors/v1.py`

추가:

- rect ROI 측정 helper
- ROI morphology helper
- `bubble_measurement_shape`에 따른 측정 분기
- delta 모드에서 baseline offset 반영
- raw / adjusted baseline 기록

동작 변화:

- `fill_ratio`
- `baseline_fill_ratio`
- `delta_fill_ratio`

모두 같은 측정 shape 기준으로 계산됩니다.

또한 `processing_meta.bubble_shape`에 실제 런타임 측정 shape를 기록합니다.

### `worker/cache.py`

템플릿 baseline cache key에 다음 값을 추가 반영했습니다.

- measurement shape
- ROI morphology 사용 여부
- ROI morphology kernel size
- ROI morphology 순서

이렇게 해서 baseline cache가 실제 측정 설정과 어긋나지 않도록 했습니다.

### 테스트

다음 파일의 테스트를 추가/수정했습니다.

- `tests/test_types.py`
- `tests/test_processors_v1.py`
- `tests/test_cache.py`
- `tests/test_scan_worker.py`

보강된 coverage:

- rect ROI delta mode
- rect ROI absolute mode
- template ink 제외 rect 측정
- cache key 분리
- draft / duplicate / teacher priority 제출 분기

## 서비스 흐름 영향

### 바뀌지 않은 것

- 백오피스는 여전히 버블 bbox 좌표를 저장
- 기존 ellipse 방식은 유지
- 템플릿 baseline cache 구조 자체는 유지

### 바뀐 것

- worker가 같은 bbox를 직사각형 ROI로 해석 가능
- baseline과 scan fill 모두 같은 rect ROI 기준으로 계산
- 최종 delta 계산 시 raw baseline이 아니라 adjusted baseline 사용

## 기대 효과

- 좌우 printed border 영향 감소
- 미마킹 버블 false positive 감소
- 새 템플릿에서 delta 분리도 개선
- 템플릿 디자인과 worker 측정 로직의 정합성 향상

## 참고

- 기존 ellipse 경로는 제거하지 않았습니다.
- 이번 변경에서 bitmap baseline 전용 모드는 아직 별도로 도입하지 않았습니다.
- ROI morphology는 기본 강제 적용이 아니라 실험 옵션입니다.

## 검증

구현 중 수행한 검증:

- worker 및 관련 테스트에 대한 `ruff`
- processors / cache / scan worker 관련 targeted pytest

`mypy worker/`는 현재 `develop`에도 존재하는 별도 이슈 때문에 여전히 실패합니다.

원인은 `worker/text_render.py`가 참조하는 `Exam` 필드와, 생성된 model/schema 간의 불일치이며 이번 rect ROI 변경과는 직접 관련이 없습니다.

