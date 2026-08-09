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
4. Files are written with 0600 permissions, directory with 0700, owned by the
   same uid/gid (1000:1000, "cardforge") that the backend/worker containers
   run as — so this script runs as root (see the `secrets-init` service's
   `user: "0:0"` override in docker-compose.yml, needed because Docker
   auto-creates the ./data/secrets bind-mount host directory as root before
   any container touches it) but immediately drops ownership of everything
   it writes down to uid 1000, rather than leaving root-owned files that a
   non-root backend container couldn't read.
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
# Not a secret, but the same Docker "bind-mount host dir gets created
# root-owned" problem applies (see module docstring rule 4) — the backend's
# Scryfall bulk sync (Phase 3) needs to write here as uid 1000.
SCRYFALL_CACHE_DIR = Path(os.environ.get("CARDFORGE_SCRYFALL_CACHE_DIR", "/data/scryfall_cache"))

# Must match the uid/gid of the "cardforge" user created in backend/Dockerfile
# (useradd --uid 1000 --gid cardforge ...), since that's the user the backend
# and worker containers actually run as when reading these files.
OWNER_UID = int(os.environ.get("CARDFORGE_SECRETS_UID", "1000"))
OWNER_GID = int(os.environ.get("CARDFORGE_SECRETS_GID", "1000"))

SECRET_SPECS: list[tuple[str, list[str]]] = [
    ("db_password", ["POSTGRES_PASSWORD", "DB_PASSWORD"]),
    ("app_secret_key", ["APP_SECRET_KEY"]),
    ("grafana_admin_password", ["GRAFANA_ADMIN_PASSWORD"]),
]


def _chown_quiet(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        # Not running as root (e.g. a manual local run outside Docker) — the
        # file/dir keeps whatever owner created it, which is fine for that
        # case since it's then already the invoking user.
        print(f"[secrets-init] WARNING: could not chown {path} to {uid}:{gid} (non-fatal)")


def resolve(filename: str, env_names: list[str]) -> None:
    path = SECRETS_DIR / filename
    if path.exists():
        path.chmod(0o600)
        _chown_quiet(path, OWNER_UID, OWNER_GID)
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
    _chown_quiet(path, OWNER_UID, OWNER_GID)


def main() -> int:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(0o700)
    _chown_quiet(SECRETS_DIR, OWNER_UID, OWNER_GID)

    for filename, env_names in SECRET_SPECS:
        resolve(filename, env_names)

    SCRYFALL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SCRYFALL_CACHE_DIR.chmod(0o755)
    _chown_quiet(SCRYFALL_CACHE_DIR, OWNER_UID, OWNER_GID)
    print("[secrets-init] scryfall_cache: ownership OK")

    print("[secrets-init] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
