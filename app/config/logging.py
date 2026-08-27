"""Structured logging setup.

Log records carry business context (operation, user, procurement, request)
through the ``extra`` mapping. Secrets are never logged: the bot token is kept
in a ``SecretStr`` and no handler ever serialises settings objects.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_CONTEXT_FIELDS = (
    "operation",
    "telegram_user_id",
    "user_id",
    "procurement_id",
    "purchase_request_id",
    "result",
    "error_type",
    "entity_type",
    "entity_id",
)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Minimal dependency-free JSON formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable local formatter that appends known context fields."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = {
            field: getattr(record, field)
            for field in _CONTEXT_FIELDS
            if getattr(record, field, None) is not None
        }
        if context:
            rendered = " ".join(f"{key}={value}" for key, value in context.items())
            base = f"{base} [{rendered}]"
        return base


def setup_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Third-party noise reduction.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
