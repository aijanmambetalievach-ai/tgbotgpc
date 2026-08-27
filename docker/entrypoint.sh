#!/bin/sh
# Container entrypoint: optionally apply migrations, then run the given command.
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] applying database migrations…"
    alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
