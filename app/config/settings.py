"""Application configuration.

Every tunable value lives here so that no magic numbers are scattered across
the codebase. Values are read from environment variables (and from a local
`.env` file during development).
"""

from __future__ import annotations

import datetime as dt
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
    default_deadline_time: str = Field(default="18:00", alias="DEFAULT_DEADLINE_TIME")

    # --- HTTP API ---------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")
    api_enabled: bool = Field(default=True, alias="API_ENABLED")

    # --- Limits -----------------------------------------------------------
    max_items_per_request: int = Field(default=500, ge=1, alias="MAX_ITEMS_PER_REQUEST")
    max_item_name_length: int = Field(default=300, ge=1, alias="MAX_ITEM_NAME_LENGTH")
    max_comment_length: int = Field(default=2000, ge=1, alias="MAX_COMMENT_LENGTH")
    max_procurement_title_length: int = Field(
        default=300, ge=1, alias="MAX_PROCUREMENT_TITLE_LENGTH"
    )
    max_procurement_description_length: int = Field(
        default=5000, ge=1, alias="MAX_PROCUREMENT_DESCRIPTION_LENGTH"
    )
    max_message_length: int = Field(default=4000, ge=100, le=4096, alias="MAX_MESSAGE_LENGTH")
    max_participants_per_procurement: int = Field(
        default=1000, ge=1, alias="MAX_PARTICIPANTS_PER_PROCUREMENT"
    )
    max_input_length: int = Field(default=8000, ge=100, alias="MAX_INPUT_LENGTH")
    #: Hard cap on an uploaded spreadsheet (Telegram itself allows up to 20 MB).
    max_upload_size_bytes: int = Field(
        default=5_000_000, ge=1_000, le=20_000_000, alias="MAX_UPLOAD_SIZE_BYTES"
    )
    #: Rows scanned in an uploaded sheet before giving up (zip-bomb guard).
    max_upload_rows: int = Field(default=5_000, ge=10, alias="MAX_UPLOAD_ROWS")
    preview_items_limit: int = Field(default=30, ge=1, alias="PREVIEW_ITEMS_LIMIT")
    page_size: int = Field(default=8, ge=1, le=50, alias="PAGE_SIZE")

    # --- Anti-spam --------------------------------------------------------
    rate_limit_messages: int = Field(default=20, ge=1, alias="RATE_LIMIT_MESSAGES")
    rate_limit_window_seconds: int = Field(default=10, ge=1, alias="RATE_LIMIT_WINDOW_SECONDS")

    # --- Invites ----------------------------------------------------------
    invite_ttl_hours: int = Field(default=72, ge=1, alias="INVITE_TTL_HOURS")

    @field_validator("app_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:  # pragma: no cover - config error
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value

    @field_validator("default_deadline_time")
    @classmethod
    def _validate_default_time(cls, value: str) -> str:
        try:
            hour_raw, minute_raw = value.split(":", 1)
            hour, minute = int(hour_raw), int(minute_raw)
        except ValueError as exc:
            raise ValueError("DEFAULT_DEADLINE_TIME must look like HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("DEFAULT_DEADLINE_TIME must be a valid time of day")
        return f"{hour:02d}:{minute:02d}"

    # --- Derived helpers --------------------------------------------------
    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def default_deadline_time_obj(self) -> dt.time:
        hour, minute = (int(part) for part in self.default_deadline_time.split(":"))
        return dt.time(hour=hour, minute=minute)

    @property
    def bootstrap_admin_ids(self) -> tuple[int, ...]:
        """Parsed list of Telegram IDs promoted to TENDER_EMPLOYEE on startup."""
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
