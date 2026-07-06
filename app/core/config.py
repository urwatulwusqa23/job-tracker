import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "Hired — AI Job Tracker"
    PORT: int = 8080
    FRONTEND_URL: str = "http://localhost:8080"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Database ─────────────────────────────────────────────────────────
    DB_PATH: str = "jobtracker.db"
    # If set (e.g. by a managed Postgres add-on, which sets this env var automatically),
    # overrides the SQLite default below.
    DATABASE_URL_OVERRIDE: str = Field(default="", validation_alias="DATABASE_URL")

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_URL_OVERRIDE:
            url = self.DATABASE_URL_OVERRIDE
            # Render/Heroku-style URLs use the legacy "postgres://" scheme; SQLAlchemy needs "postgresql://"
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url
        return f"sqlite:///{self.DB_PATH}"

    # ── Auth / JWT ───────────────────────────────────────────────────────
    SECRET_KEY: str = secrets.token_hex(32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    OAUTH_STATE_EXPIRE_MINUTES: int = 10

    # ── CORS ─────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # ── AI (xAI Grok) ────────────────────────────────────────────────────
    XAI_API_KEY: str = ""
    GROK_MODEL: str = "grok-3-mini"
    AI_BASE_URL: str = "https://api.x.ai/v1"

    # ── Google OAuth ─────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    REDIRECT_URI: str = "http://localhost:5001/auth/google/callback"
    REDIRECT_URI_LOGIN: str = "http://localhost:5001/auth/google/login/callback"

    # ── Monitoring ───────────────────────────────────────────────────────
    # Optional — if unset, Sentry is simply never initialized.
    SENTRY_DSN: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
