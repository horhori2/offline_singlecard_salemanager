# 네이버 스마트스토어 × 오프라인 재고 연동 시스템

네이버 스마트스토어 온라인 상품을 오프라인 매대와 연동하여 재고 및 주문을 통합 관리하는 대시보드입니다.

## 주요 기능

- **재고 현황** — 오프라인/네이버 재고 통합 조회, 수동 수정, 네이버 동기화
- **온라인 주문 수집** — 네이버 주문 폴링(2분), 오늘 주문 강제 재수집
- **온라인 주문 확인** — 확인 버튼 클릭 시 오프라인 재고 자동 차감
- **POS 연동** — 바코드 스캔 → 오프라인 재고 차감 → 네이버 즉시 동기화
- **오프라인 주문서** — POS 판매 영수증 조회
- **동기화 로그** — 재고 변경 이력 전체 조회

## 기술 스택

- **Backend** — FastAPI, SQLAlchemy (async), SQLite
- **Frontend** — Vanilla JS, Tabler Icons
- **API** — 네이버 커머스 API v1/v2

## 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/{username}/{repo}.git
cd {repo}

# 2. 가상환경 생성
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 네이버 API 키 입력

# 5. 서버 실행
uvicorn app.main:app --reload
```

서버 실행 후 `http://localhost:8000` 접속

## 프로젝트 구조

```
app/
├── core/
│   ├── config.py        # 환경변수 설정
│   └── database.py      # DB 연결
├── models/
│   ├── product.py       # SQLAlchemy 모델
│   └── schemas.py       # Pydantic 스키마
├── routers/
│   ├── products.py      # 상품 & 재고 API
│   └── system.py        # 동기화 & 주문 API
├── services/
│   ├── inventory.py     # 재고 비즈니스 로직
│   ├── naver_client.py  # 네이버 커머스 API 클라이언트
│   ├── order_sync.py    # 주문 폴링 & 재고 검증
│   └── excel_import.py  # 엑셀 상품 일괄 등록
└── main.py
frontend/
├── dashboard.html       # 관리자 대시보드
└── pos.html             # POS 화면
```

## 환경변수

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `NAVER_CLIENT_ID` | 네이버 커머스 API Client ID | ✅ |
| `NAVER_CLIENT_SECRET` | 네이버 커머스 API Client Secret | ✅ |
| `NAVER_ACCOUNT_ID` | 판매자 계정 ID (SELLER 타입) | 선택 |
| `DATABASE_URL` | DB 연결 문자열 | ✅ |
| `LOW_STOCK_THRESHOLD` | 재고 부족 기준 수량 (기본: 10) | 선택 |

## 주의사항

- `.env` 파일은 절대 커밋하지 마세요 (`.gitignore`에 포함됨)
- 네이버 API 키는 [네이버 커머스 API 센터](https://apicenter.commerce.naver.com)에서 발급