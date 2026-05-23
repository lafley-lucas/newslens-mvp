# NewsLens backend — Railway/Render/Fly.io 공통 호환 Dockerfile
FROM python:3.11-slim

# 보안 + 가벼움
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 — 코드 변경 시 캐시 활용
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 앱 코드
COPY app/ ./app/

# Railway/Render 등은 PORT 환경변수로 포트 주입
ENV PORT=8000
EXPOSE 8000

# uvicorn 단일 worker — in-memory 캐시/락이 worker별로 분리되므로 1개 유지 (MVP)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
