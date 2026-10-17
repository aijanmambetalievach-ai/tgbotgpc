"""Application configuration.

Every tunable value lives here so that no magic numbers are scattered across
the codebase. Values are read from environment variables (and from a local
`.env` file during development).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator
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
    #: ``0`` disables pooling: every update opens its own connection. Use it on
    #: serverless Postgres (Neon), where idle pooled connections could keep the
    #: database awake and burn the free compute hours.
    db_pool_size: int = Field(default=10, ge=0, le=100, alias="DB_POOL_SIZE")
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
    #: Hosting platforms such as Render pass the port to listen on as ``PORT``.
    api_port: int = Field(
        default=8000, ge=1, le=65535, validation_alias=AliasChoices("API_PORT", "PORT")
    )
    api_enabled: bool = Field(default=True, alias="API_ENABLED")

    # --- Webhook mode -----------------------------------------------------
    #: Public HTTPS address of this app. When set, Telegram pushes updates to
    #: ``<base>/telegram/webhook`` instead of the bot polling for them — this
    #: is what lets a free instance that sleeps when idle wake up on a message.
    #: Render provides ``RENDER_EXTERNAL_URL`` automatically.
    webhook_base_url: str = Field(
        default="", validation_alias=AliasChoices("WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL")
    )
    #: Checked against Telegram's ``X-Telegram-Bot-Api-Secret-Token`` header so
    #: nobody else can post fake updates. Letters, digits, ``_`` and ``-`` only.
    #: Optional: any string. Defaults to a value derived from the bot token.
    webhook_secret: SecretStr = Field(default=SecretStr(""), alias="WEBHOOK_SECRET")

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

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _normalize_database_url(cls, value: str | None) -> str | None:
        return normalize_database_url(value) if value else value

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
    def use_webhook(self) -> bool:
        return bool(self.webhook_base_url.strip())

    @property
    def webhook_token(self) -> str:
        """The ``secret_token`` Telegram echoes back with every webhook call.

        Hashed, because Telegram allows only ``A-Z a-z 0-9 _ -`` there while
        hosting panels generate secrets with any characters.
        """
        seed = self.webhook_secret.get_secret_value() or self.bot_token.get_secret_value()
        return hashlib.sha256(f"webhook:{seed}".encode()).hexdigest()

    @property
    def webhook_url(self) -> str:
        return self.webhook_base_url.strip().rstrip("/") + WEBHOOK_PATH

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


WEBHOOK_PATH = "/telegram/webhook"

#: libpq query options that asyncpg does not understand.
_LIBPQ_ONLY_OPTIONS = {"channel_binding", "gssencmode", "target_session_attrs"}


def normalize_database_url(url: str) -> str:
    """Accept the connection string exactly as a hosting panel shows it.

    Neon, Render and others hand out ``postgres://…?sslmode=require&…`` URLs
    meant for libpq. SQLAlchemy needs the ``postgresql+asyncpg`` driver and
    asyncpg spells the TLS option ``ssl`` — translate both.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    if scheme != "postgresql+asyncpg":
        return url.strip()
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in _LIBPQ_ONLY_OPTIONS:
            continue
        query.append(("ssl" if key == "sslmode" else key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()
