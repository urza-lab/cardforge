"""
Persistent secret resolution for the running application process.

Precedence (see SECURITY.md for rationale):
1. Persistent secret file under CARDFORGE_SECRETS_DIR, if it exists — authoritative,
   so that a changed environment variable can never silently invalidate credentials
   (e.g. the Postgres password) that are already in use.
2. Environment variable, if set.
3. Error. The web process never generates a fresh secret at request time — secret
   generation only happens once, in the dedicated `secrets-init` bootstrap step
   (see backend/scripts/init_secrets.py), so that every service consistently reads
   the same value.

Secret values are never logged or included in exception messages.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

SECRETS_DIR = Path(os.environ.get("CARDFORGE_SECRETS_DIR", "/data/secrets"))


class SecretNotAvailableError(RuntimeError):
    def __init__(self, secret_name: str):
        super().__init__(
            f"Secret '{secret_name}' is not available. Expected a persistent secret file "
            f"under {SECRETS_DIR} or the corresponding environment variable. Run the "
            f"secrets-init step (see scripts/init_secrets.py) before starting the app."
        )


def resolve_secret(file_name: str, env_names: list[str]) -> str:
    path = SECRETS_DIR / file_name
    if path.exists():
        value = path.read_text().strip()
        if value:
            return value
    for name in env_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SecretNotAvailableError(file_name)


@lru_cache(maxsize=None)
def get_db_password() -> str:
    return resolve_secret("db_password", ["POSTGRES_PASSWORD", "DB_PASSWORD"])


@lru_cache(maxsize=None)
def get_app_secret_key() -> str:
    return resolve_secret("app_secret_key", ["APP_SECRET_KEY"])
