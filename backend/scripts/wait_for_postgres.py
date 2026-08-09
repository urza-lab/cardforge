#!/usr/bin/env python3
"""Block until Postgres accepts connections, or exit non-zero after a timeout.

Used as an entrypoint step so the backend container fails fast and visibly
instead of crash-looping with an unclear error if Postgres is still starting.
"""
from __future__ import annotations

import sys
import time

import psycopg
from app.core.config import get_settings
from app.core.secrets import SecretNotAvailableError, get_db_password

TIMEOUT_SECONDS = 60
RETRY_INTERVAL_SECONDS = 2


def main() -> int:
    settings = get_settings()
    deadline = time.time() + TIMEOUT_SECONDS
    last_error: Exception | None = None

    try:
        password = get_db_password()
    except SecretNotAvailableError as exc:
        print(f"[wait-for-postgres] {exc}", file=sys.stderr)
        return 1

    while time.time() < deadline:
        try:
            with psycopg.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                dbname=settings.postgres_db,
                user=settings.postgres_user,
                password=password,
                connect_timeout=3,
            ):
                print("[wait-for-postgres] Postgres is reachable")
                return 0
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(RETRY_INTERVAL_SECONDS)

    print(f"[wait-for-postgres] timed out after {TIMEOUT_SECONDS}s: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
