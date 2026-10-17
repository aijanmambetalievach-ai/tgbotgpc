"""Application configuration.

Every tunable value lives here so that no magic numbers are scattered across
the codebase. Values are read from environment variables (and from a local
`.env` file during development).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---------------------------------------------------------
    bot_token: SecretStr = Field(default=SecretStr(""), alias="BOT_TOKEN")

    # --- Bootstrap --------------------------------------------------------
    bootstrap_admin_telegram_ids: str = Field(default="", alias="BOOTSTRAP_ADMIN_TELEGRAM_IDS")

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://tender:tender@localhost:5432/tender",
        alias="DATABASE_URL",
    )
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    db_pool_size: int = Field(default=10, ge=1, le=100, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, ge=0, le=100, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # --- Application ------------------------------------------------------
    app_env: Literal["local", "dev", "staging", "prod"] = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: Literal["json", "console"] = Field(default="console", alias="LOG_FORMAT")

    app_timezone: str = Field(default="Asia/Bishkek", alias="APP_TIMEZONE")

    # --- Branding ---------------------------------------------------------
    #: Shown in the greeting and in exported file names.
    brand_name: str = Field(default="Тендер Академия", alias="BRAND_NAME")

    # --- HTTP API ---------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")
    api_enabled: bool = Field(default=True, alias="API_ENABLED")

    # --- Limits -----------------------------------------------------------
    max_message_length: int = Field(default=4000, ge=100, le=4096, alias="MAX_MESSAGE_LENGTH")
    #: Telegram caps photo/video/document captions at 1024 characters.
    max_caption_length: int = Field(default=1000, ge=100, le=1024, alias="MAX_CAPTION_LENGTH")
    max_title_length: int = Field(default=300, ge=10, le=300, alias="MAX_TITLE_LENGTH")
    max_text_length: int = Field(default=3500, ge=100, le=3800, alias="MAX_TEXT_LENGTH")
    max_open_applications: int = Field(default=10, ge=1, alias="MAX_OPEN_APPLICATIONS")
    page_size: int = Field(default=8, ge=1, le=50, alias="PAGE_SIZE")

    # --- Anti-spam --------------------------------------------------------
    rate_limit_messages: int = Field(default=20, ge=1, alias="RATE_LIMIT_MESSAGES")
    rate_limit_window_seconds: int = Field(default=10, ge=1, alias="RATE_LIMIT_WINDOW_SECONDS")

    @field_validator("app_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:  # pragma: no cover - config error
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value

    # --- Derived helpers --------------------------------------------------
    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def bootstrap_admin_ids(self) -> tuple[int, ...]:
        """Parsed list of Telegram IDs promoted to ADMIN on startup."""
        ids: list[int] = []
        for chunk in self.bootstrap_admin_telegram_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.append(int(chunk))
            except ValueError:  # pragma: no cover - defensive
                continue
        return tuple(dict.fromkeys(ids))

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN, used by Alembic's offline mode and tooling."""
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()
