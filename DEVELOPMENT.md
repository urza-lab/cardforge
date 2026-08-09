# DEVELOPMENT

## Running in dev mode (hot reload)

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This starts:

- `backend` with `uvicorn --reload`, source mounted from `./backend/app`.
- `worker` with source mounted from `./backend/app`.
- `frontend` as a plain Vite dev server on **http://localhost:5173** (not
  port 666 — the dev frontend talks to the backend through Vite's dev proxy,
  see `frontend/vite.config.ts`, instead of the production nginx same-origin
  setup).
- `postgres` / `redis` unchanged.

## Backend only, without Docker

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export CARDFORGE_POSTGRES_HOST=localhost
export DB_PASSWORD=dev-password
export APP_SECRET_KEY=dev-secret
# requires a local Postgres + Redis, e.g.:
#   docker compose up -d postgres redis

alembic upgrade head
uvicorn app.main:app --reload
```

## Frontend only, without Docker

```bash
cd frontend
npm install
npm run dev
```

## Tests

Point `CARDFORGE_POSTGRES_DB` at a disposable database and `CARDFORGE_REDIS_DB`
at a non-zero index — not what your dev stack actually uses. The test suite
deletes/replaces table contents (including the Scryfall bulk-data mirror)
and can enqueue real RQ jobs; a `conftest.py` guard refuses to run at all
unless both are pointed away from the real ones (database name must contain
"test"; Redis DB index must not be 0, since 0 is what the real `worker`
container listens on — an enqueue there could make it perform a real sync
against the real database):

```bash
cd backend
export CARDFORGE_POSTGRES_DB=cardforge_test   # create it once: createdb / CREATE DATABASE
export CARDFORGE_REDIS_DB=1
alembic upgrade head                          # apply migrations to that database too
pytest --cov=app --cov-report=term-missing
```

CI does exactly this (see `.github/workflows/ci.yml`). If you're running via
`docker compose exec backend ...`, pass both overrides per-command:
`docker compose exec -e CARDFORGE_POSTGRES_DB=cardforge_test -e
CARDFORGE_REDIS_DB=1 backend pytest`.

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Linting / type checking

```bash
cd backend
ruff check .
mypy app
```

## Database migrations

```bash
cd backend
alembic revision --autogenerate -m "add whatever_table"
alembic upgrade head
```

Model modules must be imported in `migrations/env.py` for autogenerate to see
them (see the comment there).

## Project layout

See `ARCHITECTURE.md` for the module boundaries (`api` / `models` / `schemas`
/ `services` / `parsers` / `source_adapters` / `comparison` / `pricing` /
`refresh` / `metrics` / `workers` / `security`). The most important rule:
`app/comparison` (the comparison engine) must never import FastAPI, SQLAlchemy
sessions, or an HTTP client — it operates on plain Python dataclasses so it
stays unit-testable without a database.
