# 책등 검출 신뢰도 임계치 조정

관리자 서가 분석 화면은 YOLO 책등 검출 신뢰도 임계치를 요청별로 선택할 수 있다. 기본값은 `0.60`이며 `0.50`, `0.55`, `0.60`, `0.65`, `0.70`을 제공한다.

임계치를 높이면 낮은 신뢰도의 중복 검출을 줄일 수 있지만 실제 책등까지 누락될 수 있다. 따라서 `열외인종 잔혹사`처럼 한 권을 여러 영역으로 검출한 사례는 동일 이미지에서 `0.50`과 `0.60`을 각각 실행하고, GT 기준 Split·Precision·Recall을 함께 비교한다.

처리 흐름은 다음과 같다.

1. 백오피스가 `detection_confidence` 쿼리 파라미터를 Worker API에 전달한다.
2. Worker가 값을 검증한 뒤 Modal 요청에 포함한다.
3. Modal YOLO 추론이 해당 값을 `conf_threshold`로 사용한다.
4. 사용한 값은 로그와 결과의 `timings_seconds.detection_confidence_threshold`에 기록된다.

사용자 책 찾기 API와 기존 호출은 명시적인 값이 없으면 기존 기본값 `0.50`을 사용한다. 임계치 변경은 OCR이나 DB 매칭 점수를 직접 바꾸지 않고, 그 앞 단계에서 살아남는 책등 검출 목록만 바꾼다.

Modal 코드가 임계치를 실제 추론에 적용하므로 Worker와 백오피스 배포 외에 `modal deploy modal_app.py` 재배포가 필요하다.

## 저장된 결과 시각화

과거 실행은 재추론하지 않고 다음 URL에서 임계치 적용 결과를 확인할 수 있다.

```text
/inference/artifacts/{run_id}/confidence-visualization
  ?library_code={library_code}
  &threshold=0.60
  &focus_order={기준 검출 순서}
```

초록색은 선택 임계치 이상이라 유지되는 박스, 빨간색은 임계치 미만이라 제거되는 박스다. `focus_order`를 지정하면 기준 박스와 겹치는 후보만 확대한다. 이 화면은 저장된 NMS 이후 결과를 다시 분류하는 것이며, 저장되지 않은 NMS 이전 원시 후보를 복원하지는 않는다.
