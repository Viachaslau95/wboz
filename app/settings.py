from __future__ import annotations

from pathlib import Path

import dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str | None:
    env_local = dotenv.find_dotenv(filename="env.local", usecwd=True)
    if env_local:
        return env_local
    env_default = Path.cwd() / ".env"
    return str(env_default) if env_default.exists() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        extra="ignore",
    )

    BOT_TOKEN: str = Field(default="")
    DATABASE_URL: str = Field(default="postgresql://wboz:wboz@localhost:5432/wboz")
    DEFAULT_THRESHOLD: int = Field(ge=1, le=100)
    DEFAULT_CHECK_INTERVAL: int = Field(ge=1, le=1440)
    THRESHOLD_ALERT_COOLDOWN_HOURS: int = Field(default=24, ge=1, le=24 * 30)

    DEBUG: bool = Field(default=False)
    APP_SERVICE_NAME: str = Field(default="wboz")
    APP_ENVIRONMENT: str = Field(default="local")
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8080)
    REQUESTS_TIMEOUT: int = Field(default=10)

    DATABASE_POOL_SIZE: int = Field(default=10)
    DATABASE_POOL_MAX_OVERFLOW: int = Field(default=0)
    DATABASE_POOL_TIMEOUT: float = Field(default=30.0)

    @property
    def bot_token(self) -> str:
        return self.BOT_TOKEN

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def default_threshold(self) -> int:
        return self.DEFAULT_THRESHOLD

    @property
    def default_check_interval(self) -> int:
        return self.DEFAULT_CHECK_INTERVAL

    @property
    def database_url_sync(self) -> str:
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
            return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        return self.DATABASE_URL

    @property
    def database_url_async(self) -> str:
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        if self.DATABASE_URL.startswith("postgresql+psycopg://"):
            return self.DATABASE_URL.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        return self.DATABASE_URL


settings = Settings()  # type: ignore[call-arg] — DEFAULT_* читаются из env / env_file
