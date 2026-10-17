"""Pre-start check of DATABASE_URL, run by the container entrypoint.

Hosting logs are read by non-programmers: instead of a stack trace from deep
inside the driver, say which database host the bot tries to reach and whether
that name exists at all. The password is never printed.

    python -m app.database.check
"""

from __future__ import annotations

import socket
import sys
from urllib.parse import urlsplit

from app.config.settings import get_settings

DEFAULT_PORT = 5432


def main() -> int:
    try:
        url = get_settings().database_url
    except Exception as exc:  # pydantic explains what is wrong with the value
        print(f"[db-check] DATABASE_URL is invalid: {exc}", file=sys.stderr)
        return 1

    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or DEFAULT_PORT
    print(f"[db-check] database host: {host or '(empty)'}, port: {port}, user: {parts.username}")
    if not host:
        print(
            "[db-check] DATABASE_URL has no host. Copy the whole connection string from "
            "Neon -> Connect -> 'Copy snippet' and paste it again.",
            file=sys.stderr,
        )
        return 1
    try:
        socket.getaddrinfo(host, port)
    except socket.gaierror:
        print(
            f"[db-check] The host '{host}' does not exist. The connection string was "
            "probably copied incompletely or with a typo: copy it again from "
            "Neon -> Connect -> 'Copy snippet'.",
            file=sys.stderr,
        )
        return 1
    print("[db-check] host found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
