from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    CORS_ALLOW_ORIGINS: str = "*"
    RATE_LIMIT_PER_HOUR: int = 20

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    # 1차 모델 429(quota) 시 즉시 시도할 fallback. 무료 티어 한도가 더 넉넉하고 응답 빠름.
    GEMINI_MODEL_FALLBACK: str = "gemini-2.5-flash-lite"
    GEMINI_TIMEOUT_SECONDS: float = 60.0

    HTTP_TIMEOUT_SECONDS: float = 10.0
    MAX_ARTICLE_CHARS: int = 50_000
    MAX_SENTENCES_PER_REQUEST: int = 80  # PRD §11: 매우 긴 기사 80문장 제한

    # 기능 B — 빠진 관점 분석 (PRD §2 기능 B)
    # Google Custom Search JSON API (무료 100건/일)
    # https://developers.google.com/custom-search/v1/overview
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""
    PERSPECTIVES_MAX_RESULTS: int = 5  # LLM에 전달할 비교 기사 최대 수
    PERSPECTIVES_SEARCH_TIMEOUT: float = 8.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def perspectives_enabled(self) -> bool:
        return bool(self.GOOGLE_CSE_API_KEY and self.GOOGLE_CSE_ID)


settings = Settings()
