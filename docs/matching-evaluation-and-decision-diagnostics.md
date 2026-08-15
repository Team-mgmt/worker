# DB 매칭 평가 하네스와 관리자 판정 진단

작성일: 2026-08-15

## 호환성 원칙

기존 `DetectionResult.decision`의 `normal`, `suspected_misplacement`,
`needs_review`, `unmatched` 값은 유지한다. 기존 API 소비자와 S3
`result.json`을 깨지 않으면서 각 결과에 선택적인 `diagnostics`를 추가한다.

## 관리자 판정 진단

관리자 상세 화면은 기존 종합 상태와 함께 다음 네 축을 별도로 표시한다.

- 도서 식별: `confirmed`, `candidate`, `unmatched`
- 서가 범위: `in_range`, `out_of_range`, `unknown`
- 세부 배열: `in_order`, `out_of_order`, `unknown`
- OCR 품질: `good`, `partial`, `low`

도서 식별은 DB 후보가 자동 확정 기준을 통과했는지를 뜻한다. 서가 범위는
신뢰도 0.7 이상의 대표 KDC 10단위 범위와 비교한다. 세부 배열은 인식 가능한
청구기호가 4개 이상이고 한 권을 제외했을 때만 순서가 복원되는 경우에만 해당
책을 순서 이탈로 표시한다. 여러 책이 원인일 수 있으면 자동 지목하지 않는다.

OCR 품질은 평균 OCR 신뢰도 0.7과 제목·청구기호 인식 여부를 설명하기 위한
진단값이다. DB 매칭 또는 오배열 정답을 직접 결정하는 새 점수가 아니다.

## GT 스키마 확장

기존 polygon, 제목, 저자, 청구기호, 배치 정답에 다음 선택 필드를 추가했다.

```json
{
  "holding_id": "LibraryHolding UUID",
  "book_id": "LibraryBook UUID"
}
```

정확한 `holding_id`가 있으면 제목이 비슷하다는 이유가 아니라 실제 소장자료
정답으로 Top-1/Top-3를 평가한다. ID가 없는 기존 GT는 핵심 제목과 정규화
청구기호를 이용해 평가하므로 계속 호환된다.

GT 편집기는 예측된 소장 ID를 초기값으로 보여준다. 예측이 틀린 실패 사례에서는
검수자가 반드시 실제 `LibraryHolding.id`로 수정해야 한다.

## 평가 절차

1. S3 `result.json`을 Pydantic 스키마로 검증한다.
2. 예측 polygon과 GT polygon을 IoU 0.5 기준으로 1:1 연결한다.
3. 연결된 책등의 OCR 필드를 GT와 비교한다.
4. `top_candidates`의 holding/book ID 또는 제목·청구기호를 GT와 비교한다.
5. 자동 확정된 결과 중 Top-1이 틀린 비율을 오확정률로 계산한다.

### 책등 split/merge 평가

일반 IoU 0.5 검출 지표와 별도로 polygon 다대일·일대다 관계를 계산한다.
작은 polygon 면적의 50% 이상과 큰 polygon 면적의 10% 이상이 동시에 겹치면
두 polygon에 구조적 연관이 있다고 본다.

- GT 한 권에 예측 여러 개가 연결되면 `split`
- 예측 하나에 GT 여러 권이 연결되면 `merge`
- 연결이 없는 GT는 `missed`
- 연결이 없는 예측은 `false positive`
- 정확히 1:1이고 해당 예측이 다른 GT를 덮지 않으면 `correct`

큰 polygon의 최소 10% 조건은 책등 안의 아주 작은 잡음 검출이 split으로
집계되는 것을 막는다. 현재 50%/10%는 초기 평가 기준이며, GT 결과를 확인하기
전에는 YOLO 후처리의 자동 병합 기준으로 사용하지 않는다.

산출 지표:

- 제목 normalized accuracy
- 저자 normalized accuracy
- 청구기호 전체 exact accuracy
- KDC accuracy
- 도서기호 accuracy
- DB Top-1 accuracy
- DB Top-3 accuracy
- 자동 확정 수, 오확정 수, false confirmation rate
- correct/split/merge/missed/false-positive count
- split rate와 merge rate

분모가 0인 지표는 0으로 반환하고, 화면에 평가 건수를 함께 표시한다. 서로 다른
도서관의 결과를 합치지 말고 노원중앙 `111058`과 도봉아이나라 `111189`를
분리하여 집계한다.

## 관련 파일

- `worker/services/matching_evaluation_service.py`
- `worker/services/decision_diagnostics_service.py`
- `worker/schemas/artifact_evaluation.py`
- `worker/schemas/inference.py`
- `worker/api/artifact_evaluation.py`
- `web/apps/backoffice/src/routes/_app/evaluation/index.tsx`
- `web/apps/backoffice/src/routes/_app/shelf-ops/index.tsx`
- `tests/test_matching_evaluation_service.py`
- `tests/test_decision_diagnostics_service.py`

## 사용 방법

백오피스 GT 검수 화면에서 실행을 선택하고 각 polygon의 제목, 저자, 청구기호,
배치 정답과 소장 ID를 검수한 뒤 `GT 저장 및 평가`를 누른다. 저장된
`ground-truth.json`에 detection, placement, matching metrics가 함께 기록되고
화면 상단에 DB Top-1/Top-3와 오확정률이 표시된다.

현재 하네스는 실행 한 건의 지표를 계산한다. 여러 실행의 도서관별 집계,
난이도 태그별 비교, 이전 점수식 재생 및 latency P50/P90/P95는 다음 단계다.
