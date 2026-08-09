# ARCHITECTURE

## Design principles

1. **No AI anywhere in the core pipeline.** Import parsing, card
   normalization, oracle/printing comparison, shortfall calculation, pricing,
   refresh scheduling, filtering/sorting, dashboard metrics, and exports are
   all deterministic code with no LLM calls, no AI API keys, and no AI
   service dependency, optional or otherwise.
2. **No fake success.** Nothing in this codebase reports "done"/"ok" without
   having actually done the thing. Health checks test real connectivity;
   refresh jobs that fail are marked `FAILED`/`STALE`, not silently
   discarded; provider status reflects what actually happened.
3. **External services are optional.** With every source adapter disabled
   and Scryfall bulk auto-download turned off, the app must still start,
   accept manual imports, and run comparisons — see `QUICKSTART.md` §6.
4. **The comparison engine is a pure library.** `backend/app/comparison`
   takes plain Python data (collection contents, list contents, settings) and
   returns plain Python results. It does not import FastAPI, a SQLAlchemy
   session, or an HTTP client, so it can be unit tested in isolation and
   reused by both the API layer and background jobs.

## Phase plan

| Phase | Delivers |
|---|---|
| 1 | Compose stack, persistent secrets, FastAPI healthcheck, React/TS shell, CI skeleton |
| 2 | DB models, Alembic, collection + CSV/text/JSON import, import preview/errors |
| 3 | Scryfall normalization, oracle/printing comparison modes, user settings |
| 4 | Deck/cube detail pages, interactive tables, exports, shopping list, budget filter |
| 5 | Moxfield/Archidekt public URL adapters, refresh system, scheduler, stale handling |
| 6 | Price cache, Scryfall/MTGJSON/Cardmarket(optional)/manual providers, price profiles |
| 7 | Native dashboard, Grafana + Prometheus, collection leverage, backup docs |

Each phase is independently startable and testable; see the "Testing this
phase" note at the top of each phase's PR/commit.

## Documented default decisions

These are defaults chosen where the spec allowed OPTIONAL/IMPORTANT points to
be decided without blocking implementation. All are changeable later.

- **Auth model** (`CARDFORGE_AUTH_MODE`): the data model always supports
  multiple `users`, but the API defaults to `single-user-no-login`
  (protected only by network/reverse-proxy placement, e.g. your own
  Caddy/VPN). Setting `CARDFORGE_AUTH_MODE=multi-user` (Phase 2+) turns on
  login/session enforcement without a schema migration, since `users` always
  existed. Single-user mode is the default because CardForge is designed to
  run on a home network for one collection owner; multi-user is there for
  households/playgroups that want it.
- **License**: GPL-3.0-or-later (FOSS).
- **`migrations/` lives at `backend/migrations/`**, not at the repo root as
  the originally suggested tree in the spec showed it. Keeping it at the
  root while `alembic.ini` lives in `backend/` caused Alembic's
  `script_location` (which Alembic resolves relative to the current working
  directory, not the ini file's location) to break in two different real
  contexts — the Docker build and local/CI `cd backend && alembic ...`
  usage — because each context needed a different relative path to reach
  the same directory. Co-locating migrations with the backend that owns the
  schema removes the ambiguity entirely and is also the conventional layout
  for a FastAPI+Alembic project.
- **Data persistence**: host bind mounts under `./data/...` (not named Docker
  volumes), so backups are plain `cp`/`tar` of a visible directory next to
  the compose file — see `BACKUP_RESTORE.md`.
- **Background jobs**: a dedicated `worker` container running
  [RQ](https://python-rq.org/) against the Redis instance the stack already
  requires (no extra broker like RabbitMQ, no Celery). RQ was chosen over an
  in-process APScheduler because refresh jobs (external HTTP calls to
  Moxfield/Archidekt/Scryfall/price providers) should not share a process
  with the request-serving API — a slow/stuck external call must not affect
  API latency, and RQ jobs survive a backend container restart.
- **Reverse proxy / port 666**: the `frontend` container *is* the reverse
  proxy — an nginx image serves the built React app and proxies `/api/*` to
  the backend container, so frontend and API share one origin
  (`http://<host>:666`) with no CORS configuration needed in production. A
  separate `caddy` service for in-stack TLS is included in
  `docker-compose.yml`, commented out by default, alongside
  `caddy/Caddyfile.example` for pointing an *external* reverse proxy (e.g. a
  separate Caddy instance in another LXC container) at `<host>:666`.
- **Metrics backend**: Prometheus (`/metrics` on the backend, Phase 7) +
  Grafana reading from Prometheus, not Grafana reading Postgres directly.
  This decouples dashboards from schema changes and matches Grafana's
  primary use case (time series), at the cost of an extra service — mitigated
  by making the whole observability stack `profile: observability` (opt-in).
- **UI language**: multilingual with a dropdown, English + German shipped
  first (`frontend/src/i18n`), backed by `i18next`/`react-i18next`. There is
  no reliable external "MTG UI string" translation source to pull from —
  translations are authored and maintained in this repo as
  `src/i18n/locales/<code>.json`; adding a language is adding one file (see
  `frontend/src/i18n/index.ts`). Card names/text themselves are never
  translated — they're stored and displayed in their printed language,
  Scryfall's canonical form.
- **Scryfall bulk import**: downloads automatically on first start
  (`CARDFORGE_SCRYFALL_BULK_AUTO_DOWNLOAD=true` by default), with progress
  shown on the System Status page (Phase 3). Can be disabled in `.env` to
  trigger it manually instead.
- **UI component library**: no heavy component framework (no MUI/Mantine) —
  hand-rolled components with plain CSS (`frontend/src/styles.css`). This
  keeps the frontend dependency surface, bundle size, and upgrade burden
  minimal, which matters for a project with a "low maintenance" requirement.
  Revisit only if the interactive-table/filter requirements in Phase 4 prove
  genuinely painful without one.
- **CI image publishing**: `.github/workflows/docker.yml` builds and pushes
  to GHCR on `v*.*.*` tags. Every image is tagged with both the semver and
  the git SHA — never only `latest` — specifically so a bad release doesn't
  strand you: rolling back is pulling a previous tag, not restoring a
  deleted image. Nothing here deletes older tags.
- **Default user bootstrap** (Phase 2): the `users` row with `id = 1` is
  seeded by the initial migration's data insert (see
  `backend/migrations/versions/518d65b42f49_*.py`), not lazily created by
  the app on first request. Single-user mode has no login flow to create a
  user through, so every collection/import needs a stable owner to attach to
  from the very first request, and a migration-time seed guarantees that
  deterministically instead of depending on request ordering.
- **Collections are multi-capable, but single-user UIs don't have to know
  that** (Phase 2): the data model allows any number of named collections
  per user (matching the multi-user-ready `users` table), but
  `GET /api/collections/default` returns (creating on first call) the first
  collection ever created for a user, marked `is_default`. The Collection /
  Import UI pages use only that endpoint, so a single-collection user never
  has to think about collection IDs; multi-collection support is there for
  later phases/users who want it without a schema change.
- **Import status/source-type enums are plain `VARCHAR`, not Postgres native
  `ENUM` types** (Phase 2, see `app/models/imports.py`): a native enum needs
  an `ALTER TYPE ... ADD VALUE` migration (which can't run inside a
  transaction on older Postgres) every time a new source type or status is
  added. A `String` column validated at the Pydantic/service layer keeps
  adding one a pure application-code change.
- **Import preview rows are persisted immediately, not held in server
  memory** (Phase 2): `POST /api/imports/preview` parses the upload and
  writes one `ImportRow` per row right away, before the user has confirmed
  anything. This makes the preview step (and its per-row errors) a real,
  re-fetchable resource (`GET /api/imports/{id}`) — the confirm step is just
  "commit the rows already on this record," with no in-memory parse state to
  keep alive between requests or re-send from the client.
- **Duplicate-import detection is a flag, not a block** (Phase 2): re-
  uploading a file whose content hash matches a previously *confirmed*
  import in the same collection doesn't fail the preview — it's surfaced as
  `is_likely_duplicate` / `duplicate_of_import_id` in the preview response.
  The explicit confirm-or-abort choice IMPORT_FORMATS.md calls for is
  already the normal preview flow, so no separate "force" flag was needed.
- **Collection JSON import ships in Phase 2** alongside ManaBox CSV, generic
  CSV, and text lists (matching the phase-plan table above), even though the
  worked example in IMPORT_FORMATS.md's "JSON" section reads like a cube/deck
  list — the same `{"cards": [...]}` shape works for a flat collection, and
  building all four collection parsers together (`app/parsers/`) let them
  share one row-mapping/validation helper (`app/parsers/common.py`) instead
  of writing it three times now and a fourth time in Phase 5.

## Backend module boundaries

```
backend/app/
  api/              FastAPI routers only — no business logic
  models/           SQLAlchemy ORM models
  schemas/          Pydantic request/response schemas
  services/         Orchestration that ties models + comparison + pricing together
  parsers/          CSV/text/JSON import parsers (pure functions)
  source_adapters/  Scryfall/MTGJSON/Moxfield/Archidekt/manual adapters
  comparison/       Pure comparison engine (no FastAPI/DB/HTTP imports)
  pricing/          Price provider interface + implementations + cache
  refresh/          Scheduler + refresh state machine
  metrics/          Dashboard aggregate queries + Prometheus exporters
  workers/          RQ job functions + worker entrypoint
  security/         Auth (multi-user mode), SSRF guard for URL adapters
  core/             Settings, DB session, secrets, logging
```

## Frontend structure

Vite + React + TypeScript, `react-router-dom` for routing,
`i18next`/`react-i18next` for translations, no server-side rendering (SPA is
sufficient for a self-hosted single/few-user tool).
