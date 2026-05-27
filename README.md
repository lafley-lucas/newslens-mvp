# NewsLens — 뉴스 기사 사실/의견 분류 MVP

> "기사를 렌즈로 들여다본다" — 한국 뉴스 기사를 4가지 카테고리(FACT/CLAIM/OPINION/FRAMING)로 문장별 분류하고, 일반 독자가 인지하기 어려운 비사실 문장만 하이라이트하는 미디어 필터.

- 백엔드: Python 3.11 / FastAPI / Google Gemini 2.5-flash
- 프론트엔드: 순수 HTML/CSS/JS (모바일 퍼스트)
- 저장소: SQLite (피드백만, 원문 미저장)

## 빠른 시작 (로컬)

### 1) 백엔드
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt

# .env 작성
copy .env.example .env           # Windows
# cp .env.example .env           # macOS/Linux
# .env에 GEMINI_API_KEY 입력
# 무료 키 발급: https://aistudio.google.com/apikey

uvicorn app.main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger UI)
```

### 2) 프론트엔드
가장 간단한 방법:
```bash
cd frontend
python -m http.server 5500
# → http://localhost:5500
```
또는 `frontend/index.html`을 브라우저로 바로 열어도 동작 (CORS `*` 허용 상태).

### 3) 테스트
```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/
# 49 passed, 2 skipped (골든셋은 라벨링 후 --run-golden)
```

## 주요 API

| 메소드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 헬스체크 |
| POST | `/api/extract` | URL/텍스트 → 기사 메타 + 문장 분리 (LLM 미호출) |
| POST | `/api/analyze` | 위 + 분류 + Fact Digest (LLM 1회 통합 호출) |
| POST | `/api/perspectives` | **기능 B** — 빠진 관점 분석 (Google CSE + LLM, 비동기 호출용) |
| POST | `/api/feedback` | 사용자 피드백 (원문 미저장) |

분석 결과 구조: PRD `prd_v4_final.md` §10 참조

### 기능 B (빠진 관점 분석) 활성화 — 선택 사항

기본 배포는 기능 A+D만으로도 동작합니다. 기능 B를 켜려면 Google Custom Search 키 2개를 설정:

1. https://console.cloud.google.com → "Custom Search API" 활성화 → API 키 생성 → `GOOGLE_CSE_API_KEY`
2. https://programmablesearchengine.google.com → "전체 웹 검색" 엔진 생성 → 검색 엔진 ID → `GOOGLE_CSE_ID`
3. 두 변수를 `.env` (로컬) 또는 Railway Variables (프로덕션)에 추가 → 백엔드 재시작

미설정 시 `/api/perspectives`가 501을 반환하고 프론트는 카드를 조용히 숨깁니다 (기능 A/D는 영향 없음).

## 보안·데이터 정책

- **SSRF 차단**: 사설 IP/localhost/AWS metadata 자동 차단
- **Rate limit**: IP당 시간당 20회 (in-memory sliding window)
- **In-flight 락**: 동일 URL 동시 처리 시 한 번만
- **캐시**: URL 분석 결과 24h TTL (텍스트 입력은 캐시 제외)
- **원문 미저장**: 피드백 DB는 URL의 sha256 hash + 문장 index + 카테고리만

## 배포

### 백엔드 (Railway 권장)
1. Railway 대시보드에서 새 프로젝트 → GitHub 리포지토리 연결
2. Root 디렉토리: 그대로 (railway.toml이 backend/ 하위를 빌드 컨텍스트로 지정)
3. Variables에 다음 환경변수 추가:
   - `GEMINI_API_KEY` — 필수
   - `GEMINI_MODEL` — 선택 (기본 gemini-2.5-flash)
   - `CORS_ALLOW_ORIGINS` — 프론트 URL (예: `https://lafley-lucas.github.io`)
   - `APP_ENV=production`
4. Deploy → 자동 헬스체크 `/api/health` 통과 확인

### 프론트엔드 (GitHub Pages)
GitHub Pages의 branch 모드는 `/`와 `/docs`만 지원하므로, `frontend/` 폴더는 GitHub Actions로 배포합니다 (`.github/workflows/deploy-pages.yml`이 이미 설정돼 있음).

1. GitHub repo Settings → Pages
2. **Source**: `GitHub Actions` 선택 (Deploy from a branch 아님)
3. `frontend/`에 변경이 들어오는 main push마다 Actions가 자동 배포
4. Actions 탭에서 빌드 완료 후 `https://<user>.github.io/<repo>/` 활성화

배포 후 `frontend/index.html`의 inline config 활성화:
```html
<script>
  window.NEWSLENS_API_BASE = "https://your-app.up.railway.app";
</script>
```

CORS를 위해 Railway 환경변수 `CORS_ALLOW_ORIGINS`도 GitHub Pages 도메인으로 제한 권장.

## 프로젝트 구조

```
mvp 제작/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 엔트리 + CORS
│   │   ├── api/routes.py       # /api/health, /extract, /analyze, /feedback
│   │   ├── services/
│   │   │   ├── fetcher.py      # URL → 본문 (trafilatura → newspaper4k → fusion)
│   │   │   ├── fusion_parser.py # Arc Publishing(조선닷컴) 전용
│   │   │   ├── splitter.py     # kss 한국어 문장 분리
│   │   │   ├── classifier.py   # Gemini 분류 + Fact Digest (1회 호출)
│   │   │   ├── url_guard.py    # SSRF 차단
│   │   │   ├── content_guard.py # 짧음/비한국어/오피니언 휴리스틱
│   │   │   ├── rate_limiter.py # IP 시간당 20
│   │   │   ├── in_flight.py    # 동일 URL 동시 처리 락
│   │   │   ├── cache.py        # 24h TTL 결과 캐시
│   │   │   └── db.py           # SQLite 피드백
│   │   ├── models/schemas.py   # Pydantic
│   │   └── config.py
│   ├── tests/                  # pytest (49 passed)
│   ├── Dockerfile / Procfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html              # 입력/로딩/결과 4-state
│   ├── style.css               # 모바일 퍼스트, 보라 액센트
│   ├── app.js                  # 상태머신 + 모드 토글 + 피드백 + 토스트
│   └── .nojekyll               # GitHub Pages 보조
├── railway.toml                # 배포 설정
├── prd_v4_final.md             # 제품 기획서
└── README.md
```

## 라이선스

내부 MVP — 라이선스 미정.
