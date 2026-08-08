#!/usr/bin/env python3
"""
CardForge persistent secrets initializer.

Run once at stack startup (see the `secrets-init` service in docker-compose.yml)
before Postgres, the backend, or Grafana start. Resolves DB_PASSWORD /
POSTGRES_PASSWORD, APP_SECRET_KEY and GRAFANA_ADMIN_PASSWORD, generating
cryptographically secure random values when needed, and persists them under
/data/secrets/*.

Rules (see SECURITY.md):
1. If a persistent secret file already exists, it is authoritative. Environment
   variables are ignored for that secret. This is deliberate: it prevents a
   changed/misconfigured environment variable from silently breaking
   credentials (e.g. Postgres auth) that are already in use after a restart.
2. Otherwise, the first non-empty environment variable in the candidate list
   seeds the persistent file.
3. Otherwise, a cryptographically secure random value is generated.
4. Files are written with 0600 permissions, directory with 0700.
5. Secret values are never logged.
6. This script never overwrites an existing secret file. Use
   scripts/reset-secrets.sh to deliberately rotate a secret.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

SECRETS_DIR = Path(os.environ.get("CARDFORGE_SECRETS_DIR", "/data/secrets"))

SECRET_SPECS: list[tuple[str, list[str]]] = [
    ("db_password", ["POSTGRES_PASSWORD", "DB_PASSWORD"]),
    ("app_secret_key", ["APP_SECRET_KEY"]),
    ("grafana_admin_password", ["GRAFANA_ADMIN_PASSWORD"]),
]


def resolve(filename: str, env_names: list[str]) -> None:
    path = SECRETS_DIR / filename
    if path.exists():
        path.chmod(0o600)
        print(f"[secrets-init] {filename}: persistent secret already present, keeping it")
        return

    value: str | None = None
    used_env: str | None = None
    for name in env_names:
        v = os.environ.get(name, "").strip()
        if v:
            value = v
            used_env = name
            break

    if value is None:
        value = secrets.token_urlsafe(48)
        print(f"[secrets-init] {filename}: generated new random value")
    else:
        print(f"[secrets-init] {filename}: initialized from ${used_env}")

    path.write_text(value)
    path.chmod(0o600)


def main() -> int:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SECRETS_DIR.chmod(0o700)
    except PermissionError:
        print(f"[secrets-init] WARNING: could not chmod {SECRETS_DIR} (non-fatal)")

    for filename, env_names in SECRET_SPECS:
        resolve(filename, env_names)

    print("[secrets-init] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
