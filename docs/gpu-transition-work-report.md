# GPU 추론 전환 및 운영 작업 총정리

작성일: 2026-08-14

## 목적과 범위

ShelfAlign의 YOLO OBB 책등 검출과 PaddleOCR를 기존 AWS CPU worker에서
Modal NVIDIA L4로 이전한 이유, 구현 과정, 장애 수정, 성능 결과 및 운영
절차를 정리한다.

GPU로 이전한 것은 비전 추론 부분뿐이다. 다음 구성은 계속 AWS에 남아 있다.

- FastAPI 공개 API 및 요청 오케스트레이션
- PostgreSQL RDS 도서 후보 조회와 재정렬
- 정상/오배열/검수 필요 판정
- S3 원본·annotated 이미지·crop·`result.json` 저장
- NestJS 백엔드와 React 백오피스

## CPU 기준선

기존 EC2는 GPU가 없는 약 1GB RAM 환경이었다. 34권 표본에서 책 한 권당 OCR
로그가 대략 3.9~5.8초였고, 전체 요청은 1분을 넘기거나 경우에 따라 2분에
가까워졌다. 모델과 웹 서비스를 동시에 실행하면 swap 사용과 메모리 압박도
발생했다.

CPU 경로에서 다음 최적화를 먼저 수행했다.

- OBB perspective crop
- 하단 청구기호 영역 OCR
- 저신뢰 결과에만 CLAHE, sharpen, 90/270도 회전 fallback
- 여러 crop을 contact sheet로 묶는 일괄 OCR
- 사용자 목표 도서 검색의 조기 종료 및 정밀 OCR 재시도

이 작업들은 GPU 이전 후에도 그대로 사용된다. GPU는 기존 파이프라인을
대체한 것이 아니라 동일한 검출·crop·OCR 로직을 가속한다.

## 공급자 검토

### AWS GPU EC2

항상 켜 두면 콜드스타트 없이 예측 가능한 지연시간을 제공하지만, 유휴 시간에도
비용이 발생하고 CUDA/드라이버 및 별도 배포 운영이 필요하다. MVP 트래픽에는
고정비가 크다고 판단해 보류했다.

### fal.ai

커스텀 serverless 앱을 구현했지만 배포 권한이 거부됐다. 지원팀 답변상 해당
기능은 Enterprise 또는 월 수천 달러 이상의 고사용량 고객을 대상으로 하므로
현재 규모에서는 제외했다.

### Modal

커스텀 Python 컨테이너, NVIDIA L4, 초 단위 사용량 과금, scale-to-zero,
비공개 프록시 인증 및 영구 모델 Volume을 사용할 수 있어 MVP에 채택했다.

## 최종 구조

```text
모바일/백오피스
  -> AWS EC2 FastAPI worker
  -> 비공개 Modal endpoint
       -> YOLO OBB 검출
       -> perspective crop/contact sheet
       -> PaddleOCR GPU 추론
  -> AWS EC2 RDS 매칭 및 최종 판정
  -> S3 artifact 저장
  -> API 응답
```

활성 설정:

- GPU: NVIDIA L4
- `min_containers=0`: 요청이 없으면 scale-to-zero
- `max_containers=1`: 동시 GPU 컨테이너와 비용 제한
- `scaledown_window=600`: 마지막 요청 후 10분간 웜 상태 유지
- Modal proxy token으로 비공개 endpoint 인증
- PaddleOCR 모델을 Modal Volume에 캐시
- Modal 실패 시 AWS CPU fallback

`scaledown_window=600`은 10분마다 과금하는 타이머가 아니다. 요청 후 컨테이너를
최대 10분간 유지하며, 요청이 전혀 없으면 컨테이너도 생성되지 않는다.

## 주요 구현 작업

1. `modal_app.py`에 YOLO와 PaddleOCR GPU 실행 환경 구성
2. 모델 및 worker 코드를 Modal 이미지에 포함
3. EC2에서 이미지를 base64 JSON으로 비공개 endpoint에 전송
4. bbox, OBB polygon, confidence, detected order 및 OCR 진단값 반환
5. 관리자 `/inference/analyze_vision`과 사용자
   `/inference/find_target_book` 모두 원격 비전 경로 연결
6. 실패 시 기존 로컬 CPU 추론으로 복귀
7. 사용자 검색 결과도 관리자 결과와 같은 S3 구조에 저장
8. 목표 도서의 청구기호와 가까운 최대 3권에만 정밀 OCR 재시도
9. 모델 SHA256과 provider 및 단계별 시간을 `result.json`에 저장
10. 원격 관리자 경로에 매칭과 S3 저장 시간 로그 추가

주요 커밋:

- `a59076f`: Modal GPU offload 도입
- `b1f77a8`: 웜 유지 시간을 10분으로 변경
- `dd1c56e`: 초기 GPU 의사결정 및 벤치마크 문서
- `a86d6c9`: 사용자 목표 검색 S3 artifact 저장
- `842e0fd`: 목표 후보에 대한 적응형 정밀 OCR
- `f641dc1`, `75510ea`: Modal 의존성 및 DB 결합 문제 수정
- `8538d6a`, `fcc13c3`: 제목 OCR 변형 강제 재시도
- `367deaf`: 원격 관리자 매칭/S3 관측 로그

## 전환 중 해결한 장애

### fal.ai 배포 권한 거부

코드 문제가 아니라 계정 권한 정책이었다. fal.ai 구현을 운영 경로에서 제외하고
Modal로 전환했다.

### Modal 이미지의 `rapidfuzz` 누락

목표 매칭 모듈을 가져오는 과정에서 `ModuleNotFoundError: rapidfuzz`가 발생했다.
필요 패키지를 Modal 이미지에 명시적으로 추가했다.

### DB 드라이버 결합

Modal이 목표 매칭 유틸리티를 import할 때 DB 모델과 `psycopg`까지 연쇄적으로
불러와 실패했다. 원격 비전/목표 매칭이 RDS 연결 없이 실행되도록 결합을
분리했다. DB 접근은 EC2 worker만 담당한다.

### 정밀 OCR이 청구기호만 재인식

`천하무적 불량야구단`처럼 표지가 손글씨이고 세로 배치된 책은 라벨
`813.6 주67ㅊ`은 읽지만 제목을 읽지 못했다. 청구기호가 유력한 후보에는
제목용 회전·전처리 변형을 강제로 실행하도록 변경했다. 단, OCR이 실제 제목을
읽지 못하면 정확 청구기호 일치만으로 자동 `found`하지 않고 `possible`로
보수적으로 반환한다.

### S3 위치가 `unknown`으로 저장

사용자 화면의 `library_code` 전달 및 artifact 저장 경로를 수정하여
`shelfalign/scans/{library_code}/...` 아래에 저장되도록 했다.

### 관리자 원격 경로 관측 부족

초기에는 Modal 왕복 시간만 기록되어 DB와 S3 병목을 구분할 수 없었다.
현재는 다음 로그를 별도로 남긴다.

```text
remote vision done ... round_trip=...
matching start ...
matching done elapsed=...
artifacts saved prefix=... elapsed=...
```

## 실제 성능 결과

### 사용자 목표 도서 검색

35개 검출 책등의 초기 관찰값:

| 상태 | Detection | OCR | 원격 왕복/전체 | 결과 |
|---|---:|---:|---:|---|
| Cold | 8.4초 | 4.5초 | 47.6초 | 콩가루 수사단 order 13, 93.3 |
| Cold | 8.6초 | 5.0초 | 37.1초 | 콩가루 수사단 order 13, 93.3 |
| Warm | 0.1초 | 2.2초 | 4.7초 | 사막으로 떠난 인어 order 26, 87.7 |
| Warm | 0.1초 | 2.3초 | 4.6초 | 저장된 후속 검색 |

### 관리자 서가 분석

커밋 `367deaf` 배포 후 동일한 35개 검출 책등에서 측정했다.

| 상태 | Detection | OCR | Modal 왕복 | DB 매칭 | S3 저장 | 추정 전체 |
|---|---:|---:|---:|---:|---:|---:|
| Cold | 13.6초 | 8.5초 | 51.3초 | 0.8초 | 2.7초 | 약 54.8초 |
| Warm | 0.1초 | 3.1초 | 5.6초 | 0.6초 | 2.1초 | 약 8.3초 |

해석:

- 웜 상태에서는 관리자 모드도 S3 저장을 포함해 10초 이내다.
- 35권 DB 매칭 0.6초는 현재 주요 병목이 아니다.
- 웜 GPU의 YOLO 0.1초, OCR 3.1초로 CPU 대비 큰 폭으로 개선됐다.
- 첫 요청의 37~54초는 모델 초기화와 컨테이너 콜드스타트 영향이 크다.
- 이 수치는 고정 GT 하네스의 반복 측정이 아니라 운영 로그 관찰값이다.

## 배포와 운영

Modal 앱 변경 시 개발 PC에서 배포한다.

```cmd
cd C:\dev\comp_lib\worker
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m modal deploy modal_app.py
```

일반 EC2 worker 코드만 변경한 경우 Modal 재배포는 필요 없다.

```bash
cd /opt/shelfalign
git pull --ff-only origin main
sudo systemctl restart shelfalign-worker.service
sudo systemctl is-active shelfalign-worker.service
```

관리자 분석 단계별 로그:

```bash
sudo journalctl -u shelfalign-worker.service \
  --since "10 minutes ago" \
  --no-pager -o cat | \
  grep -Ei 'remote vision done|matching start|matching done|artifacts saved|artifacts skipped|artifact save failed|fallback'
```

시연 직전 같은 이미지로 한 번 요청하여 컨테이너를 웜업한다. 이후 요청을
10분 이내에 유지하면 웜 지연시간을 기대할 수 있다. 키와 토큰은 `.env`에만
저장하며 로그, 문서, 코드 또는 Git에 넣지 않는다.

## 비용 및 안정성 보호

- Modal workspace budget과 usage limit을 유지한다.
- `max_containers=1`로 갑작스러운 병렬 비용을 제한한다.
- 콜드와 웜 요청을 분리하여 비용과 지연시간을 기록한다.
- CPU fallback은 장애 대응용이며 정상 운영 성능 목표로 사용하지 않는다.
- 동시 요청이 하나의 컨테이너를 기다리면 웜 요청도 대기시간이 증가할 수 있다.

## 남은 과제

1. 노원중앙과 도봉아이나라 GT를 분리 구축
2. cold 10회 이상, warm 30회 이상 반복 측정
3. latency P50/P90/P95 및 최대 메모리 기록
4. OCR CER/WER와 청구기호 exact accuracy 측정
5. 사용자 목표 검색 Top-1 및 위치 정확도 측정
6. 관리자 DB matching Top-1/Top-3 및 오확정률 측정
7. Modal GPU 초와 스캔당 비용 측정
8. S3 업로드를 응답 후 비동기로 전환할지 안정성과 함께 비교
9. 트래픽 증가 시 `max_containers`, Modal 비용과 AWS GPU EC2 비용 재비교

현재 결론은 “Modal L4 웜 상태에서 시연 목표인 10초 이내를 달성했다”이다.
정확도와 비용에 대한 최종 주장은 동일 이미지·동일 GT·동일 설정의 반복
평가 이후에만 확정한다.
