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
   run as — except a secret only some other specific service reads (e.g.
   grafana_admin_password, owned by grafana's own uid instead — see
   SECRET_SPECS), which is owned by that service's uid/gid instead. This
   script runs as root (see the `secrets-init` service's `user: "0:0"`
   override in docker-compose.yml, needed because Docker auto-creates the
   ./data/secrets bind-mount host directory as root before any container
   touches it) but immediately drops ownership of everything it writes down,
   rather than leaving root-owned files a non-root container couldn't read.
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
# Same problem again for the optional observability stack (Phase 7,
# `--profile observability`) - prom/prometheus and grafana/grafana-oss run
# as their own fixed non-root users, and Docker still creates these
# bind-mount host dirs as root on first start.
PROMETHEUS_DATA_DIR = Path(os.environ.get("CARDFORGE_PROMETHEUS_DATA_DIR", "/data/prometheus"))
GRAFANA_DATA_DIR = Path(os.environ.get("CARDFORGE_GRAFANA_DATA_DIR", "/data/grafana"))

# Must match the uid/gid of the "cardforge" user created in backend/Dockerfile
# (useradd --uid 1000 --gid cardforge ...), since that's the user the backend
# and worker containers actually run as when reading these files.
OWNER_UID = int(os.environ.get("CARDFORGE_SECRETS_UID", "1000"))
OWNER_GID = int(os.environ.get("CARDFORGE_SECRETS_GID", "1000"))

# prom/prometheus's image USER (Config.User: "nobody", numeric 65534:65534
# in that image) - confirmed via `docker run --rm --entrypoint sh
# prom/prometheus:v3.1.0 -c id`.
PROMETHEUS_UID = 65534
PROMETHEUS_GID = 65534
# grafana/grafana-oss's image USER (Config.User: "472", group 0/root - an
# arbitrary-uid-friendly pattern some images use instead of a dedicated
# group, confirmed the same way). Directory is made group-writable (0775)
# rather than owned outright by gid 0, since gid 0 is also root's group and
# a plain chown wouldn't be enough on its own to grant grafana write access.
GRAFANA_UID = 472
GRAFANA_GID = 0

# Third element overrides the default (OWNER_UID, OWNER_GID) for secrets
# only one specific non-cardforge service ever reads - grafana_admin_password
# is read solely by the grafana container (GF_SECURITY_ADMIN_PASSWORD__FILE),
# never by backend/worker, so it's owned by grafana's own uid (472) instead
# of the shared 1000:1000 the backend-readable secrets use.
SECRET_SPECS: list[tuple[str, list[str], tuple[int, int] | None]] = [
    ("db_password", ["POSTGRES_PASSWORD", "DB_PASSWORD"], None),
    ("app_secret_key", ["APP_SECRET_KEY"], None),
    ("grafana_admin_password", ["GRAFANA_ADMIN_PASSWORD"], (472, 0)),
]


def _chown_quiet(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        # Not running as root (e.g. a manual local run outside Docker) — the
        # file/dir keeps whatever owner created it, which is fine for that
        # case since it's then already the invoking user.
        print(f"[secrets-init] WARNING: could not chown {path} to {uid}:{gid} (non-fatal)")


def resolve(filename: str, env_names: list[str], owner: tuple[int, int] | None) -> None:
    owner_uid, owner_gid = owner if owner is not None else (OWNER_UID, OWNER_GID)
    path = SECRETS_DIR / filename
    if path.exists():
        path.chmod(0o600)
        _chown_quiet(path, owner_uid, owner_gid)
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
    _chown_quiet(path, owner_uid, owner_gid)


def main() -> int:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(0o700)
    _chown_quiet(SECRETS_DIR, OWNER_UID, OWNER_GID)

    for filename, env_names, owner in SECRET_SPECS:
        resolve(filename, env_names, owner)

    SCRYFALL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SCRYFALL_CACHE_DIR.chmod(0o755)
    _chown_quiet(SCRYFALL_CACHE_DIR, OWNER_UID, OWNER_GID)
    print("[secrets-init] scryfall_cache: ownership OK")

    PROMETHEUS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROMETHEUS_DATA_DIR.chmod(0o755)
    _chown_quiet(PROMETHEUS_DATA_DIR, PROMETHEUS_UID, PROMETHEUS_GID)
    print("[secrets-init] prometheus: ownership OK")

    GRAFANA_DATA_DIR.mkdir(parents=True, exist_ok=True)
    GRAFANA_DATA_DIR.chmod(0o775)
    _chown_quiet(GRAFANA_DATA_DIR, GRAFANA_UID, GRAFANA_GID)
    print("[secrets-init] grafana: ownership OK")

    print("[secrets-init] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
