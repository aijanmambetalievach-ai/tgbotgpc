"""Text normalisation, sanitisation and safety helpers.

Everything here is pure and dependency-free so it can be unit-tested without a
database, Telegram or Excel.
"""

from __future__ import annotations

import html
import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Characters Excel/LibreOffice may interpret as the start of a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def normalize_unicode(value: str) -> str:
    """NFC-normalise and drop control characters (keeps newlines and tabs out)."""
    normalized = unicodedata.normalize("NFC", value)
    return _CONTROL_CHARS.sub("", normalized)


def collapse_whitespace(value: str) -> str:
    """Collapse runs of spaces/tabs, trim lines, cap consecutive blank lines."""
    value = _MULTI_SPACE.sub(" ", value)
    value = "\n".join(line.strip() for line in value.split("\n"))
    return _MULTI_NEWLINE.sub("\n\n", value).strip()


def sanitize_text(value: str | None, max_length: int) -> str:
    """Normalise, collapse and hard-truncate arbitrary user input."""
    if not value:
        return ""
    cleaned = collapse_whitespace(normalize_unicode(value))
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned


def sanitize_filename(value: str, max_length: int = 120, fallback: str = "file") -> str:
    """Produce a safe, Unicode-friendly file name.

    Cyrillic is preserved (the business wants readable names), but path
    separators, Windows-reserved characters and control codes are removed and
    the result can never be empty, a traversal fragment, or a reserved name.
    """
    cleaned = _UNSAFE_FILENAME.sub("_", normalize_unicode(value))
    cleaned = cleaned.replace("..", "_").strip(" ._")
    cleaned = _MULTI_SPACE.sub("_", cleaned)
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("_ ")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if not cleaned or cleaned.lower() in reserved:
        return fallback
    return cleaned


def sanitize_excel_cell(value: object) -> object:
    """Neutralise Excel/CSV formula injection.

    Any string starting with a formula trigger is prefixed with an apostrophe
    so spreadsheet software treats it as literal text instead of evaluating it.
    Non-string values (numbers, dates, ``Decimal``) are returned untouched.
    """
    if not isinstance(value, str):
        return value
    stripped = value.lstrip("​﻿")
    if stripped.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def escape_html(value: str) -> str:
    """Escape text before embedding it into an HTML-parse-mode message."""
    return html.escape(value, quote=False)


def truncate(value: str, max_length: int, suffix: str = "…") -> str:
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - len(suffix))].rstrip() + suffix


_PHONE_DIGITS = re.compile(r"\D+")
#: Kyrgyz national numbers: 9 digits after the 996 country code.
KG_COUNTRY_CODE = "996"
KG_NATIONAL_LENGTH = 9
MIN_PHONE_DIGITS = 9
MAX_PHONE_DIGITS = 15


def normalize_phone(raw: str | None) -> str | None:
    """Normalise a phone number to ``+<digits>``; ``None`` when it is not one.

    Local Kyrgyz formats (``0555 12 34 56``, ``555123456``) get the ``+996``
    country code; any other international number is kept as typed.
    """
    if not raw:
        return None
    digits = _PHONE_DIGITS.sub("", raw)
    if len(digits) == KG_NATIONAL_LENGTH + 1 and digits.startswith("0"):
        digits = KG_COUNTRY_CODE + digits[1:]
    elif len(digits) == KG_NATIONAL_LENGTH:
        digits = KG_COUNTRY_CODE + digits
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return None
    return f"+{digits}"


_HTML_TAG = re.compile(r"<[^>]+>")


def html_to_plain(value: str) -> str:
    """Strip Telegram HTML down to plain text (for previews that get truncated —
    cutting HTML in the middle could leave an unclosed tag)."""
    return html.unescape(_HTML_TAG.sub("", value))
