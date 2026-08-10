# BACKUP_RESTORE

**Verified (Phase 7):** `scripts/backup.sh` was run against the real running
stack and produced a real ~83MB dump (532,469 Scryfall printings, 592,966
price observations, 2,653 collection items); restoring that dump into a
disposable scratch database (never the real `cardforge` one) reproduced
identical row counts across every major table, confirming the dump/restore
mechanism itself round-trips correctly.

## What needs backing up

CardForge state lives entirely under `${CARDFORGE_DATA_DIR}` (default
`./data`, a host bind mount next to `docker-compose.yml` — see
`ARCHITECTURE.md` for why bind mounts were chosen over named volumes):

| Path | Contents | Sensitivity |
|---|---|---|
| `./data/postgres` | All application data (collection, decks, cubes, comparisons, prices, settings) | High |
| `./data/secrets` | `db_password`, `app_secret_key`, `grafana_admin_password` | High |
| `./data/scryfall_cache` | Downloaded Scryfall bulk data | Low (re-downloadable) |
| `./data/redis` | Job queue state only, safely disposable | Low |
| `./data/grafana` | Grafana's own settings (only if the `observability` profile is used) | Low |
| `./data/prometheus` | Prometheus's own time-series data (only if the `observability` profile is used) — every value it holds is re-derived from `/metrics` on the next scrape anyway, so this is purely a "keep dashboard history" backup, not a "recover state" one | Low |

**`./data/postgres` and `./data/secrets` must be backed up together.** A
Postgres dump alone is not enough — restoring it against a fresh
`secrets-init` run would generate a *new* `db_password`, which won't match
the role password already set inside that Postgres data directory (see
`SECURITY.md`).

## Backup

```bash
./scripts/backup.sh
```

This produces a compressed `pg_dump` at
`./data/backups/cardforge_<timestamp>.sql.gz`. Copy this file **and** the
entire `./data/secrets/` directory to your backup destination — e.g.:

```bash
tar czf cardforge-backup-$(date +%Y%m%d).tar.gz \
  ./data/backups/cardforge_*.sql.gz ./data/secrets
```

For a full filesystem-level backup instead of a SQL dump, stop the stack
first so Postgres isn't writing mid-copy:

```bash
docker compose down
tar czf cardforge-full-backup-$(date +%Y%m%d).tar.gz ./data
docker compose up -d
```

## Restore

```bash
./scripts/restore.sh path/to/cardforge_TIMESTAMP.sql.gz
docker compose restart backend worker
```

For a full filesystem restore, stop the stack, replace `./data` with the
backed-up copy (including `secrets`), then start again:

```bash
docker compose down
rm -rf ./data
tar xzf cardforge-full-backup-YYYYMMDD.tar.gz
docker compose up -d
```

## Update process

```bash
git pull
docker compose pull   # if using published GHCR images, see docker-compose.yml
docker compose up -d --build
```

Alembic migrations run automatically on backend startup (see
`backend/scripts/entrypoint.sh`) — no manual migration step needed.
Published images are tagged with both a semver and a git SHA and are never
overwritten in place (see `.github/workflows/docker.yml`), so rolling back a
bad update is:

```bash
docker compose pull backend@<previous-tag>   # or edit the image tag in docker-compose.yml
docker compose up -d
```

Take a backup (above) before any update that changes the major version.

## Restart behavior

A plain `docker compose restart` or host reboot does **not** lose data or
regenerate secrets — Postgres, Redis, and secrets all live on bind mounts
outside the containers. The backend waits for Postgres to become reachable
before running migrations and starting (see
`backend/scripts/wait_for_postgres.py`), so a slower-starting Postgres after
a host reboot does not cause a crash loop.
