"""Deployment-related settings: hosting connection strings, port, webhook."""

from __future__ import annotations

import re

import pytest
from pydantic import SecretStr

from app.config.settings import WEBHOOK_PATH, Settings, normalize_database_url
from app.database.session import connect_args_for


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?ssl=require",
        ),
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        (
            "postgresql+asyncpg://tender:tender@localhost:5432/tender",
            "postgresql+asyncpg://tender:tender@localhost:5432/tender",
        ),
    ],
)
def test_hosting_connection_strings_are_accepted_as_is(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_pooled_neon_host_disables_prepared_statement_cache() -> None:
    pooled = "postgresql+asyncpg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/db?ssl=require"
    direct = "postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/db?ssl=require"
    args = connect_args_for(pooled)
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]() != args["prepared_statement_name_func"]()
    assert connect_args_for(direct) == {}


def test_platform_port_and_url_are_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://tender-bot.onrender.com/")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.api_port == 10000
    assert settings.use_webhook
    assert settings.webhook_url == f"https://tender-bot.onrender.com{WEBHOOK_PATH}"


def test_polling_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(name, raising=False)
    assert not Settings(_env_file=None).use_webhook  # type: ignore[call-arg]


def test_webhook_token_is_always_valid_for_telegram() -> None:
    base = Settings(_env_file=None, BOT_TOKEN="1:abc")  # type: ignore[call-arg]
    generated = base.model_copy(update={"webhook_secret": SecretStr("a+b/c==")})
    for settings in (base, generated):
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", settings.webhook_token)
    assert base.webhook_token != generated.webhook_token
