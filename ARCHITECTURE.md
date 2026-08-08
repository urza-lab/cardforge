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
