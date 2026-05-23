from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    CORS_ALLOW_ORIGINS: str = "*"
    RATE_LIMIT_PER_HOUR: int = 20

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: float = 60.0

    HTTP_TIMEOUT_SECONDS: float = 10.0
    MAX_ARTICLE_CHARS: int = 50_000
    MAX_SENTENCES_PER_REQUEST: int = 80  # PRD §11: 매우 긴 기사 80문장 제한

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]


settings = Settings()
