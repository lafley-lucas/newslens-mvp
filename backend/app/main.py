from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="NewsLens API",
        version="0.1.0",
        description="뉴스 기사 사실/의견 분류 및 핵심 사실 요약 서비스",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()
