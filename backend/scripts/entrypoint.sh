#!/bin/sh
# Entrypoint for the backend container: wait for Postgres, run Alembic
# migrations (Phase 2+), then start the API server.
set -e

python /app/scripts/wait_for_postgres.py

if [ -d /app/migrations ] && [ -f /app/alembic.ini ]; then
  echo "[entrypoint] running database migrations..."
  alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
