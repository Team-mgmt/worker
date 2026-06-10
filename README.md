# ShelfAlign AI - Worker ⚙️

ShelfAlign AI는 2026 도서관 데이터 활용 공모전을 위해 개발된 **스마트폰 기반 도서관 서가 오배열 탐지 및 도서 탐색 서비스**입니다. 
이 레포지토리(worker)는 영상 처리, AI 객체 탐지, OCR 파이프라인, 공공데이터 수집 및 매칭을 담당하는 핵심 백엔드 서버입니다. 프론트엔드(web)로부터 전달받은 이미지를 분석하여 구조화된 결과를 반환합니다.

> ⚠️ **주의**: 본 프로젝트는 공모전 출품용 MVP 버전으로 🚧 현재 일부 기능이 구현 중(WIP)에 있습니다. 모델의 학습 가중치(.pt) 및 공공 API 인증키 등은 보안상 `.gitignore` 처리되어 레포지토리에 포함되지 않습니다.

---

## 🏗 전체 시스템 구조

서비스는 프론트엔드(`web`)와 백엔드(`worker`)로 나뉘어 동작합니다. 본 레포지토리는 하단의 Worker AI 파이프라인 전체를 담당합니다.

```text
[ Web (Client) ]       [ Worker (FastAPI Server) ]
+--------------+       +-------------------------------------------------+
|              |       | 1. 서가 라벨 OCR -> 현재 서가 KDC 범위 추정             |
|   이미지 전송  | ----> | 2. 책등 검출 (YOLOv8)                             |
|              |       | 3. 책등 OCR (텍스트 추출)                           |
|              |       | 4. NL API 보정 (퍼지 매칭)                          |
|   JSON 결과   | <---- | 5. 장서 DB (도서관 정보나루) 매칭                     |
|              |       | 6. 오배열 판정 (KDC 예외 케이스 처리) / 이용자 탐색 판정 |
+--------------+       +-------------------------------------------------+
```

워커 서버는 두 가지 모드의 판정 로직을 지원합니다:
- **사서 모드**: 서가 전체를 스캔하여 검출된 도서들을 DB와 대조한 뒤, 현재 서가 범위를 벗어난 도서를 찾아냅니다.
- **이용자 모드**: 목표 도서(도서명, 청구기호 등)의 메타데이터를 입력받아 현재 프레임 내에 퍼지 매칭으로 유사한 후보가 존재하는지 이진 판정(Binary classification)합니다.

---

## 🧠 AI 파이프라인 상세

### 1. 서가 라벨 OCR
- **Input**: 서가 전체 이미지
- **Output**: 현재 서가의 KDC 범위 (예: `810~819 한국문학`)
- 촬영된 서가 최상단이나 측면에 부착된 도서관 자체 분류 라벨을 인식하여 기준점을 설정합니다.

### 2. 책등 검출 (Spine Detection)
- **Input**: 서가 전체 이미지
- **Output**: 개별 책등의 Bounding Box 좌표 배열
- **Model**: YOLOv8 (자체 구축한 책등 데이터셋으로 Fine-tuning)

### 3. 책등 OCR
- **Input**: 잘려진 책등 이미지 텐서
- **Output**: Raw Text (도서명, 저자명, 청구기호 등 혼재)
- **Model**: 🚧 EasyOCR / PaddleOCR (실험 및 평가 진행 중)

### 4. OCR 결과 보정
- **Input**: 책등 Raw Text
- **Output**: 보정된 메타데이터 (제목, 저자, ISBN)
- OCR 인식 오류를 최소화하기 위해 **국립중앙도서관 ISBN/소장자료 API**를 활용하여 검색 가능한 유효 데이터로 후보군을 교정합니다.

### 5. 장서 DB 매칭
- **Input**: 보정된 메타데이터
- **Output**: 매칭된 도서의 도서관 소장 정보 (정확한 KDC, 청구기호 등)
- 사전 구축된(도서관 정보나루 `itemSrch`) PostgreSQL DB에서 해당 도서를 검색합니다.

### 6. 오배열 판정 & 이용자 탐색 판정
- **사서 모드 (오배열 판정)**: 매칭된 도서의 KDC가 1단계에서 추정한 서가 범위에 속하는지 검사합니다. (단, 별치기호, 복본, 참고도서 등 도서관별 예외 룰 적용)
- **이용자 모드 (탐색 판정)**: 입력받은 목표 도서와 OCR 결과의 유사도 거리를 측정하여 임계값 이상일 경우 "후보 감지"로 판정하고 프레임 내 위치(Bounding Box 중심점)를 반환합니다.

### 7. 결과 반환
- **Output**: JSON (인식된 전체 도서 목록, 오배열 후보 리스트, 각 객체의 신뢰도 점수 및 Bounding Box 위치)

---

## 📊 공공 데이터 및 API 연동

1. **도서관 정보나루 libSrch API**
   - **용도**: 서울 소재 타겟 도서관들의 고유 `libCode` 수집 (DB화 완료)
2. **도서관 정보나루 itemSrch API**
   - **용도**: 특정 도서관의 전체 장서 DB 구축 (도서명, 저자, ISBN, KDC, 청구기호 필드 활용)
   - **상태**: 초기 1회 구축 후 주기적 수동 업데이트 🚧
3. **국립중앙도서관 ISBN/소장자료 API**
   - **용도**: 불안정한 OCR 텍스트를 퍼지 매칭으로 교정하여 유효한 도서 정보 후보 추출
4. **서울 열린데이터광장 서울도서관 소장자료 데이터**
   - **용도**: KDC 분포 분석 및 오배열 빈발 구간(EDA) 사전 분석 (모델 성능 검증용)

---

## 🛠 기술 스택

- **Runtime**: Python 3.10+
- **API Server**: FastAPI / Uvicorn
- **AI / Vision**: PyTorch, Ultralytics (YOLOv8), OpenCV, EasyOCR/PaddleOCR
- **Database**: PostgreSQL, SQLAlchemy
- **Queue**: 🚧 SQS 또는 내부 메모리 큐 (도입 예정)
- **Infrastructure**: 🚧 AWS EKS / EC2 기반 배포 환경 (예정)

---

## 🚀 로컬 실행 방법

```bash
# 1. 가상환경 생성 및 의존성 설치
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. 서버 실행
uvicorn main:app --reload --port 8000
```

---

## ⚙️ 환경 변수

프로젝트 최상단의 `.env` 파일에 다음 항목들을 설정해야 합니다.

```env
DATABASE_URL=postgresql://user:password@localhost:5432/shelfalign
JUNGBO_NARU_API_KEY=your_jungbo_naru_key_here
NL_API_KEY=your_nl_api_key_here
AWS_REGION=ap-northeast-2
```

---

## 📂 레포지토리 구조

```text
/worker
  ├── /api             # FastAPI 라우터 및 엔드포인트
  ├── /models          # Pydantic 스키마 및 DB 모델
  ├── /pipeline        # 1~7단계 AI 및 매칭 파이프라인 비즈니스 로직
  ├── /data            # 더미 데이터 및 초기 설정용 파일들
  ├── /scripts         # 데이터 수집 및 전처리 유틸리티 스크립트
  ├── /training        # YOLOv8 모델 학습 및 평가 코드
  ├── main.py          # 애플리케이션 진입점
  └── requirements.txt # Python 패키지 의존성
```

---

## 📥 데이터셋 수집 방법 🚧

장서 DB 및 모델 파인튜닝용 데이터를 수집하는 스크립트가 `/scripts` 디렉토리에 포함되어 있습니다.

```bash
# 장서 DB 수집 실행 예시 (준비 중)
python scripts/collect_library_items.py --libcode 111000
```

---

## 🎓 모델 학습 및 추론 🚧

본 프로젝트는 도서관 환경에 최적화된 책등 검출을 위해 직접 구축한 커스텀 데이터셋으로 YOLOv8 모델을 학습합니다.
- 사전 학습 모델: `yolov8s.pt`
- 학습 코드 및 설정 파일은 `/training` 하위에 위치합니다.

---

## 📈 평가 지표 (예상치) 🚧

본 MVP 파이프라인의 내부 목표 평가 지표는 다음과 같습니다.
- **책등 검출 (Object Detection)**: mAP@0.5 **85%** 이상
- **책등 텍스트 OCR 정확도 (CER)**: 한글/영숫자 혼용 기준 CER **15%** 미만
- **오배열 탐지 성능**: 정밀도(Precision) **80%**, 재현율(Recall) **75%** 이상

---

## 🔗 관련 레포지토리

- 사서 및 이용자용 모바일 프론트엔드 및 관리자 대시보드: [shelfalign-web](링크 추가 예정)

---

## 👥 팀 정보

ShelfAlign 팀은 2026 도서관 데이터 활용 공모전을 위해 구성되었습니다.

- **임준수** - Project Manager & Full-stack Engineer
- **팀원 A** - AI / Computer Vision Engineer
- **팀원 B** - Backend Data Engineer
- **팀원 C** - UX/UI Designer
