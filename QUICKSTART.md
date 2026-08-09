# QUICKSTART

Get CardForge running on a Linux host (LXC container or VM) with Docker and
Docker Compose already installed.

## 1. Requirements

- Linux with a modern kernel (any distro that supports Docker's `overlay2`
  storage driver — this includes standard Proxmox/LXC and Debian/Ubuntu VMs).
- Docker Engine 24+ and the Docker Compose plugin (`docker compose version`
  should print v2.x).
- ~2 GB RAM free for the stack at idle (Postgres, Redis, backend, worker,
  frontend). The optional Scryfall bulk card database adds a few hundred MB
  of disk once downloaded.
- Outbound HTTPS access to `api.scryfall.com` (and optionally
  `mtgjson.com`, `moxfield.com`, `archidekt.com`) if you want automatic card
  data / price / decklist syncing. **All of these are optional** — CardForge
  is fully usable with everything imported manually and no outbound network
  access at all (see "Working fully offline" below).

If you're in an unprivileged LXC container: no special container features
(no `privileged: true`, no extra capabilities) are required — Docker running
inside the container is enough.

## 2. Get the repository

```bash
git clone https://github.com/urza-lab/cardforge.git
cd cardforge
```

## 3. Configure

```bash
cp .env.example .env
```

Open `.env` and adjust `CARDFORGE_HOST_PORT` (default `666`) and
`CARDFORGE_DATA_DIR` (default `./data`, a bind-mounted directory next to the
compose file — see `BACKUP_RESTORE.md`) if needed. You do **not** need to set
any passwords — see "Secrets" below.

## 4. Start the stack

```bash
docker compose up -d --build
```

First start does the following automatically:

1. `secrets-init` generates and persists `db_password`, `app_secret_key`,
   and `grafana_admin_password` under `./data/secrets/` (only if you didn't
   set them yourself in `.env`).
2. Postgres and Redis start.
3. The backend waits for Postgres, runs Alembic migrations, and starts.
4. If `CARDFORGE_SCRYFALL_BULK_AUTO_DOWNLOAD=true` (the default), the backend
   downloads the Scryfall bulk card database in the background (~110k
   printings, ~20s); progress is visible on the **System Status** page in
   the UI, with a manual "Sync now" button there too.
5. The frontend (nginx, serving the built React app and proxying `/api`) is
   published on `${CARDFORGE_HOST_PORT}` (default **666**).

## 5. Open the app

```
http://<host-ip>:666
```

Check `http://<host-ip>:666/api/health/ready` for a JSON readiness report
(Postgres/Redis connectivity) — this is also what the container healthchecks
use.

## 6. Working fully offline

Set `CARDFORGE_SCRYFALL_BULK_AUTO_DOWNLOAD=false` before first start, and
leave every source in **Sources** disabled. Every import path (collection,
decks, cubes) also accepts manual CSV/text/JSON uploads with no network
calls at all — see `IMPORT_FORMATS.md`.

## Secrets

You never need to invent or type passwords. If you want a *specific* value
(e.g. to match an externally managed Postgres), set `POSTGRES_PASSWORD` (or
`DB_PASSWORD`), `APP_SECRET_KEY`, or `GRAFANA_ADMIN_PASSWORD` in `.env`
*before the first start*. See `SECURITY.md` for exact precedence rules and
how to rotate a secret later.

## Stopping / restarting

```bash
docker compose down        # stops containers, keeps ./data
docker compose up -d       # starts again with the same data/secrets
```

A restart never generates new secrets or loses data — see `SECURITY.md` and
`BACKUP_RESTORE.md`.
