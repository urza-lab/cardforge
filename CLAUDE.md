# CardForge — CLAUDE.md

Context for Claude Code picking up this project. See `README.md` for the
product description and `ARCHITECTURE.md` for the full phase plan and
documented design decisions — read both before making changes.

## Status (updated after Phase 2)

Phase 1 (Docker Compose skeleton, persistent secrets, FastAPI healthcheck,
React/TS shell) is **complete and verified working end-to-end** on a
Proxmox LXC (Debian, Docker + Compose v2).

Phase 2 (DB models, Alembic migrations, collection import — ManaBox CSV,
generic CSV, text lists, JSON, import preview/errors) is **complete and
verified end-to-end**: `docker compose up -d --build` brings up all six
services `Up`/`healthy` (including `frontend`, see gotcha #11 below);
`/api/health/ready` reports postgres/redis OK; a full
upload → preview → confirm round trip was exercised through the real nginx
proxy (`POST /api/imports/preview` → `POST /api/imports/{id}/confirm` →
`GET /api/collections/{id}/items`), not just against the backend directly.
51 backend tests pass (`pytest`, 92% coverage on the new code); `ruff`,
`mypy`, and the frontend `lint`/`typecheck`/`build` are all clean.

Repo: `https://github.com/urza-lab/cardforge` (public). Tags `v0.1.0-phase1`
through `v0.1.3-phase1` mark the incremental Phase 1 fixes described below.

**Next up: Phase 3** (Scryfall normalization, oracle/printing comparison
modes, user settings). See `ARCHITECTURE.md` for the full 7-phase plan and
"Documented default decisions" for the Phase 2 choices made along the way
(default-user bootstrap, `/collections/default`, enum-as-VARCHAR, import
preview persistence, duplicate-import flagging, JSON collection import).

## Environment

- Dev/test machine: Windows 11 + PowerShell (git, GitHub CLI `gh`, Python
  3.12, Node.js LTS all installed via winget/npm during Phase 1 setup).
- Runtime/test target: a Debian LXC container on Proxmox VE, Docker +
  Compose v2 installed, reachable at `docker.trusted.local:666`.
- GitHub push access is only confirmed from the Windows machine (`gh auth
  login` there). The LXC currently only has read access (public repo, plain
  `git clone`/`git pull` — no push credentials configured there). If you
  want the LXC to push directly, that needs its own auth setup first.

## Hard-won gotchas from Phase 1 (don't rediscover these)

1. **`migrations/` must live at `backend/migrations/`, not the repo root.**
   Alembic resolves `script_location` relative to the *current working
   directory*, not `alembic.ini`'s own location. Since CI and local dev both
   run `cd backend && alembic ...`, and the Docker image also uses
   `backend/` as its build context, migrations has to be a sibling of
   `alembic.ini` inside `backend/` for this to work consistently everywhere.
2. **Backend Docker build context is `./backend`** (not the repo root) —
   keep it that way; `backend/Dockerfile`'s `COPY` paths assume it.
3. **`backend/scripts/entrypoint.sh`'s executable bit is set explicitly at
   build time** (`RUN chmod +x scripts/*.sh scripts/*.py` in
   `backend/Dockerfile`) rather than relied upon from git. A Windows
   checkout of this repo can silently lose the Unix executable bit (NTFS
   doesn't have one), which breaks the container with `permission denied`
   at startup if not baked in at build time.
4. **`secrets-init` runs as root** (`user: "0:0"` in `docker-compose.yml`)
   because Docker auto-creates the `./data/secrets` bind-mount host
   directory as root on first start, before any container touches it — a
   non-root container can't write into it. `backend/scripts/init_secrets.py`
   chowns everything it creates back to uid:gid 1000:1000 (the `cardforge`
   user backend/worker actually run as) so the files stay 0600 and readable
   only by that user.
5. **`worker`'s Docker healthcheck is disabled** (`healthcheck: disable:
   true`) — it inherits the backend image's HTTP-based healthcheck, but the
   worker process has no HTTP server, so that check would always fail.
6. **Ruff is pinned to `0.8.4`** in `backend/requirements-dev.txt` — verify
   any lint fix against that exact version if debugging CI, not whatever
   version happens to be installed globally (a newer local ruff can report
   clean when the pinned CI version wouldn't, or vice versa).
7. **No `.dockerignore` at the repo root** — it's scoped to
   `backend/.dockerignore` since the backend build context is `./backend`.
   Don't reintroduce a repo-root one without checking whether the build
   context changed again.
8. **Frontend needs both `@eslint/js` and `typescript-eslint`** as
   devDependencies for the flat-config `eslint.config.js` to resolve — these
   were missing initially and broke `npm run lint` in CI.
9. **`backend/scripts/entrypoint.sh` must end with `exec "$@"`, not a
   hardcoded `exec uvicorn ...`** (fixed in Phase 2). It used to ignore
   whatever command was passed to the container entirely, which meant
   `docker-compose.dev.yml`'s override (`entrypoint: [wait_for_postgres.py]`
   + a different `command:` for `--reload`) silently never ran the command
   half — the backend container just crash-looped on "waiting for postgres"
   forever in dev mode. `Dockerfile` now sets a default `CMD` and
   `entrypoint.sh` execs whatever it's given after waiting/migrating, so
   `docker-compose.dev.yml` only needs to override `command:`, not
   `entrypoint:`.
10. **`backend/Dockerfile`'s `COPY --from=build-deps ... /home/cardforge/.local`
    needs `--chown=cardforge:cardforge`** (fixed in Phase 2). Without it the
    copied packages stay root-owned; the app still runs fine (world-readable
    files), but the non-root `cardforge` user can never `pip install --user`
    anything into that same prefix afterwards (e.g. dev tools for ad-hoc
    debugging in a running container) — silently `Permission denied`.
11. **`frontend/nginx.conf` must `listen` on both `80` and `[::]:80`**
    (fixed in Phase 2). The container `HEALTHCHECK` probes
    `http://localhost/healthz`, and the container's `/etc/hosts` resolves
    `localhost` to `::1` before `127.0.0.1`; an IPv4-only `listen 80;` made
    every healthcheck fail with "connection refused" even though the proxy
    itself worked perfectly (`curl :666/api/...` always succeeded) — the
    `frontend` container just permanently showed `unhealthy` in
    `docker compose ps`.

## Principles to keep enforcing in later phases

- **No AI/LLM anywhere in the core pipeline.** Import parsing, card
  normalization, comparison, pricing, refresh, metrics — all deterministic.
- **No fake success.** Health checks, refresh jobs, and provider status must
  reflect what actually happened, never a hardcoded "ok".
- **External services stay optional.** The app must fully start and be
  usable (manual imports at minimum) with every source adapter disabled.
- The comparison engine (`backend/app/comparison`, Phase 3+) must stay a
  pure library with no FastAPI/SQLAlchemy-session/HTTP imports.

## Testing a change

```bash
cd ~/cardforge   # on the LXC
docker compose down
docker compose up -d --build
docker compose ps -a          # everything should be "Up"/"healthy", nothing stuck at "Created"
curl -s http://localhost:666/api/health/ready | jq
```

Backend: `cd backend && ruff check . && mypy app && pytest`
Frontend: `cd frontend && npm run lint && npm run build`
