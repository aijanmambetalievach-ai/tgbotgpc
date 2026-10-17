#!/bin/sh
# Container entrypoint: optionally apply migrations, then run the given command.
set -eu

# Fail early, with a readable message, if the database address is wrong.
python -m app.database.check

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] applying database migrations…"
    alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
