# CardForge — CLAUDE.md

Context for Claude Code picking up this project. See `README.md` for the
product description and `ARCHITECTURE.md` for the full phase plan and
documented design decisions — read both before making changes.

## Status (updated after Phase 6)

Phase 1 (Docker Compose skeleton, persistent secrets, FastAPI healthcheck,
React/TS shell) is **complete and verified working end-to-end** on a
Proxmox LXC (Debian, Docker + Compose v2).

Phase 2 (DB models, Alembic migrations, collection import — ManaBox CSV,
generic CSV, text lists, JSON, import preview/errors) is **complete and
verified end-to-end**, including a real upload → preview → confirm round
trip through the nginx proxy, not just against the backend directly.

Phase 3 (Scryfall normalization, oracle/printing comparison modes, user
settings) is **complete and verified end-to-end against real data**: a real
bulk sync against `api.scryfall.com` landed 110,571 printings in ~20s; the
user's real 2,653-card ManaBox-imported collection resolved 100% exactly
against it (`POST /api/collections/{id}/resolve`); real decklist comparisons
were run against that real collection through the nginx proxy
(`POST /api/comparisons/run`), both oracle and printing mode. 99 backend
tests pass (`pytest`, 91% coverage); `ruff`, `mypy`, and the frontend
`lint`/`typecheck`/`build` are all clean. `docker compose down && docker
compose up -d --build` was verified to bring all six services back
`Up`/`healthy` with the real collection and Scryfall mirror intact
(bind-mounted Postgres data, not re-synced/re-imported).

Phase 4 (deck/cube data model + manual text/JSON import, detail pages,
interactive tables, CSV exports, shopping list) is **complete and verified
end-to-end against real data**: a real deck (mainboard + commander +
sideboard, via text import) was imported through the nginx proxy, resolved
against the real Scryfall mirror, compared against the user's real
2,653-card collection (`GET /api/lists/{id}/comparison`), exported to CSV,
and included in a real shopping-list call — all through the proxy, not just
against the backend directly. Note "budget filter" moved to Phase 6 and
manual deck/cube import moved here from Phase 5 — see ARCHITECTURE.md.
A real bug was caught by the end-to-end smoke test specifically (not by the
unit/API test suite, which hadn't exercised the case) — see gotcha #14.

Also added during Phase 4, user-requested after the phase's initial
completion: per-card display-name language (`app/services/
display_name_service.py`), each card shown by default in whatever language
its own import data recorded, with a "force language" override in Settings
(German/English/auto). This required switching the Scryfall bulk mirror
from `default_cards` to `all_cards` (see ARCHITECTURE.md) — verified with a
real sync: **532,468** printings in ~3m15s (vs. `default_cards`'~110k/~20s).
Re-resolving the real collection against the new mirror still hit 100%
exact (2,653/2,653); with the language setting on auto, **2,601 of 2,653**
real collection items got a translated display name (the rest are cards
with no German printing to mirror at all) — a `card_name_language: "en"`
override correctly reverted all of them to English in the same live check.

153 backend tests pass; `ruff`, `mypy`, and the frontend
`lint`/`typecheck`/`build` are all clean.

Phase 5 (Moxfield/Archidekt public URL adapters, deck/cube CSV import,
refresh system, scheduler, stale handling) is **complete and verified
end-to-end against real data and real live third-party APIs**: a real
Moxfield deck (`moxfield.com/decks/R3Nv7DlrokW5uPuriAGBng`, 92 cards) and a
real Archidekt deck (`archidekt.com/decks/1/fun_with_fungus`, 17 cards) were
both fetched live during development; a real deck was imported from a
Moxfield URL through the nginx proxy, resolved against the real Scryfall
mirror, and refreshed — the refresh ran on the real `worker` container,
made a real live call to `api.moxfield.com`, and flipped
`FETCHING`→`CURRENT` in under a second. A real deck/cube CSV (with
`section`/`category`/`tags` columns) was imported the same way. The SSRF
guard (`app/security/ssrf_guard.py`) was verified against both a real
external host (example.com, allowed) and real internal targets (localhost,
`backend`, `169.254.169.254`, `127.0.0.1` — all blocked). A full `docker
compose down && docker compose up -d --build` was verified to bring all six
services back `Up`/`healthy` with the real 2,653-card collection and the
real 532,468-row Scryfall mirror intact, followed by a fresh URL import +
refresh cycle against the newly-built containers (not just the
pre-restart ones). 212 backend tests pass (91% coverage); `ruff`, `mypy`,
and the frontend `lint`/`typecheck`/`build` are all clean. The new frontend
pages (Sources, the "from URL" import mode, per-list refresh controls) were
verified via the built production bundle serving correctly and containing
the new strings/routes — **not** via an actual browser click-through, since
no browser-automation tool was available in this session; treat the UI as
lint/typecheck/build-verified but not feature-verified until someone
clicks through it once. See `ARCHITECTURE.md` "Documented default
decisions" for the Phase 5 design choices (adapters reuse `ParseResult`
instead of SOURCE_ADAPTERS.md's aspirational types, SSRF guard's manual
per-hop redirect re-validation, deck/cube CSV as its own parser, refresh
state machine vs. computed staleness, wholesale item replacement on
refresh, the catch-all failure handler, and the plain-thread staleness
sweep instead of RQ's scheduler).

Phase 6 (price cache, Scryfall/MTGJSON/manual price providers, price
profiles, budget filter) is **complete and verified end-to-end against real
data and real live third-party APIs**: a real MTGJSON price sync landed
**298,285** real price observations (TCGplayer USD + Cardmarket EUR retail,
joined from `AllIdentifiers.json.xz` + `AllPricesToday.json`) in under two
minutes; a real Scryfall resync (triggered specifically to exercise the new
piggybacked price extraction) landed **294,681** real Scryfall-sourced price
observations alongside its normal 532,469-printing card mirror sync; the
real 2,653-card collection was re-resolved to 100% exact
(`POST /api/collections/{id}/resolve`) afterward, matching the same pattern
established in Phase 4. A real Moxfield deck import (92 cards) and a real
Archidekt deck import (17 cards) were both priced end-to-end
(`GET /api/lists/{id}/comparison?price_profile_id=...`) with real resolved
USD prices for every missing card, and a real `$50` budget filter
correctly allocated `$48.54` cheapest-first across 80 missing cards. Two
real data-integrity bugs were found and fixed via these live syncs, not
caught by the unit/API test suite alone (see gotchas #19 and #20) — both
now also covered by regression tests. **No direct Cardmarket API adapter**
was built (MTGJSON already relays real Cardmarket EUR retail data — see
PRICING.md and ARCHITECTURE.md). A full `docker compose down && docker
compose up -d --build` was verified to bring all six services back
`Up`/`healthy` with the real collection and both real price syncs intact,
followed by a fresh real Archidekt import + priced budget comparison
against the newly-built (not just pre-restart) containers. 251 backend
tests pass (91% coverage); `ruff`, `mypy`, and the frontend
`lint`/`typecheck`/`build` are all clean. As with Phase 5's frontend work,
the new UI (Prices page, price profile management, budget filter controls
on the list comparison card) was verified via the built production bundle
serving correctly and containing the new strings/routes through the real
nginx proxy — not via an actual browser click-through, since no
browser-automation tool was available in this session either.

Repo: `https://github.com/urza-lab/cardforge` (public). Tags `v0.1.0-phase1`
through `v0.1.3-phase1` mark the incremental Phase 1 fixes described below.
The LXC has its own push access — SSH deploy key
(`~/.ssh/cardforge_deploy`, write access, scoped to this one repo only),
remote set to `git@github.com:urza-lab/cardforge.git`. No separate `gh` CLI
install on the LXC.

**Next up: Phase 7** (native dashboard, Grafana + Prometheus, collection
leverage, backup docs). See `ARCHITECTURE.md` for the full 7-phase plan and
"Documented default decisions" for the choices made along the way
(default-user bootstrap, `/collections/default`,
enum-as-VARCHAR, import preview persistence, duplicate-import flagging, JSON
collection import, the single denormalized `scryfall_cards` table,
resolution matching priority, ad-hoc non-persisted comparisons, minimal
`user_settings` table, the separate list-import pipeline, text-list section
semantics, multi-list shopping-list pooling, the Phase 5/6 decisions above).

## Environment

- Dev/test machine: Windows 11 + PowerShell (git, GitHub CLI `gh`, Python
  3.12, Node.js LTS all installed via winget/npm during Phase 1 setup).
- Runtime/test target: a Debian LXC container on Proxmox VE, Docker +
  Compose v2 installed, reachable at `docker.trusted.local:666`.
- GitHub push access from the Windows machine: `gh auth login` there.
  The LXC has its own, separate push access as of Phase 3: an SSH deploy key
  (`~/.ssh/cardforge_deploy`, "Allow write access", scoped to only this repo)
  with `origin` set to `git@github.com:urza-lab/cardforge.git`. No `gh` CLI
  installed on the LXC — plain `git push`/`pull` only.

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
12. **`./data/scryfall_cache` has the same root-ownership problem as
    `./data/secrets`** (found in Phase 3, fixed the same way as gotcha #4):
    Docker creates the bind-mount host directory as root on first start, and
    nothing chowned it to uid 1000 before the Scryfall bulk sync tried to
    write there. Fixed by mounting it into `secrets-init` too and having
    `init_secrets.py` chown it, same pattern as the secrets directory.
13. **Tests must point `CARDFORGE_POSTGRES_DB` at a disposable database and
    `CARDFORGE_REDIS_DB` at a non-zero index** (Phase 3) — enforced by a
    hard `pytest_configure` guard in `backend/tests/conftest.py` that raises
    before any test runs otherwise. `scryfall_cards` holds ~110k rows of
    real reference data a test's cleanup deletes/repopulates, and
    Scryfall-sync tests enqueue real RQ jobs onto whatever Redis DB is
    configured — at index 0 (the default) that's the same one the real
    `worker` container listens on, so an ill-configured test run could make
    the real worker perform a real sync against the real database. See
    DEVELOPMENT.md "Tests".
14. **A `relationship()` to a NOT NULL foreign-keyed child needs
    `passive_deletes=True` (or ORM-level `cascade="all, delete-orphan"`) or
    deleting the parent 500s** (found in Phase 4 via the end-to-end smoke
    test, not the unit tests — see `app/models/collection.py`
    `Collection.imports` and `app/models/lists.py` `CardList.imports`).
    Without one of those two, SQLAlchemy's default behavior on parent
    delete is to `UPDATE ... SET child_fk = NULL` for every related child
    row before deleting the parent — which fails outright when that FK
    column is `NOT NULL` (as `imports.collection_id` and
    `list_imports.list_id` both are), even though the column already has
    `ON DELETE CASCADE` at the database level. `passive_deletes=True` tells
    the ORM to trust that DB-level cascade instead of managing it itself.
    The bug was invisible to `test_delete_list` because that test deleted a
    list with *no* import history — the failure only triggers when a related
    child row actually exists, which the real E2E smoke test happened to
    have (a real imported deck) and the original unit test didn't.
15. **After `docker compose up -d --build <service>`, verify the running
    container's image ID actually matches the freshly built one** — don't
    trust the compose CLI output alone (found in Phase 4: rebuilding
    `frontend` right after rebuilding `backend` produced a new image, but
    the *running* `frontend` container kept using the previous one; no
    "Recreate" line appeared in the compose output either). `docker inspect
    <container> --format '{{.Image}}'` vs. `docker inspect <image>:latest
    --format '{{.Id}}'` catches the mismatch; `docker compose up -d
    --force-recreate <service>` fixes it. Cause unconfirmed (possibly a
    compose quirk when rebuilding multiple services back-to-back) — treat
    the verification step as routine, not just a one-off fix.
16. **A running `worker` container can silently be missing
    `docker-compose.dev.yml`'s bind mount even when `backend` has it**
    (found in Phase 5): `docker compose restart worker` does *not* re-apply
    compose file overrides — it was still running a 13-hours-stale image
    with no `./backend/app:/app/app` mount, so newly added job functions
    (`app/workers/jobs.py`) didn't exist in that container's view of the
    module, and RQ's `import_attribute` failed with a confusing
    `AttributeError`/`ValueError: Invalid attribute name` deep inside `rq`
    rather than a normal Python `ImportError`. `docker inspect
    cardforge-worker --format '{{range .Mounts}}...'` showed the mount
    genuinely missing; `docker compose -f docker-compose.yml -f
    docker-compose.dev.yml up -d --force-recreate worker` fixed it. Same
    root cause as gotcha #15 (a running container silently out of sync with
    the current compose config) but via `restart` instead of `up --build` —
    treat "does this container's actual mounts/image match what the
    compose files currently say" as something to verify after *any*
    container lifecycle command during dev work, not just rebuilds.
17. **The production image only installs `requirements.txt`, not
    `requirements-dev.txt`** (confirmed in Phase 5, not a new decision —
    `backend/Dockerfile` has always had a single `runtime` target) — `ruff`/
    `mypy`/`pytest` are only present in a container that either bind-mounts
    the dev tools in some other way or had them `pip install --user`'d
    manually into its writable layer. Recreating that container (`up
    --build`, `--force-recreate`) wipes a manual install since it's not
    baked into the image. For verifying a *plain prod build* (as CLAUDE.md's
    own "Testing a change" recipe does), `docker cp` the
    `requirements-dev.txt`/`requirements.txt`/`tests/`/`data/examples`
    paths into the running container and `pip install --user -r
    requirements-dev.txt` first, or just use `docker compose -f
    docker-compose.yml -f docker-compose.dev.yml` for the container you
    intend to run dev tooling against instead.
18. **A long-running `worker` process caches old code in memory even with
    the correct bind mount** (found repeatedly in Phase 6): unlike
    `uvicorn --reload`'s file-watching restart, `python -m
    app.workers.run_worker` has no hot-reload — Python's own module
    caching (`sys.modules`) means a worker process that already imported
    `app.workers.jobs`/`app.source_adapters.*` keeps using whatever was on
    disk when *it* started, forever, regardless of later edits landing on
    the (correctly mounted) host filesystem. `docker compose exec worker
    python -c "import app.workers.jobs as m; print(hasattr(m, '...'))"`
    is misleading here — it always shows `True` for a new function because
    `exec` spawns a *fresh* process that imports fresh, while the actual
    long-running worker still has the stale version. Symptom is the exact
    same confusing `rq.utils.import_attribute` `AttributeError`/`ValueError:
    Invalid attribute name` as gotcha #16's missing-mount case, but the fix
    here is different: `docker compose restart worker` (a real process
    restart, not `--force-recreate`, and not just checking the mount) after
    *any* edit to code the worker executes, before triggering a job that
    exercises it.
19. **A `db.execute(delete(Parent))` inside a bulk-sync loop cascade-deletes
    *every* child row referencing it, not just the ones that sync is about
    to replace** (found in Phase 6 against real data: `run_bulk_sync`'s
    full `scryfall_cards` wipe-then-reinsert was cascading away *all*
    `price_observations` rows — manual and MTGJSON prices included, not
    just Scryfall's own — every time someone re-synced the card mirror,
    even though the same IDs get reinserted moments later in the same
    transaction). If a child table's rows should survive a parent's
    delete-and-reinsert cycle, snapshot the child rows you don't own before
    the delete and restore them after, filtered to IDs that still exist in
    the new data — see `app/source_adapters/scryfall.py` `run_bulk_sync`'s
    `preserved_prices`/`restorable` handling and PRICING.md.
20. **Two independent batch counters flushed on separate size thresholds
    can flush out of dependency order** (found in Phase 6 against real
    data, a `ForeignKeyViolation` on a real Scryfall sync): `run_bulk_sync`
    accumulated `ScryfallCard` rows and their `PriceObservation` rows in
    two separate lists, each flushed independently once *its own* list hit
    `BATCH_SIZE` — since one card produces up to 4 price rows but only 1
    card row, the price list reliably filled up (and flushed) before the
    card list did, inserting price rows whose card wasn't in the database
    yet. Fixed by triggering both flushes off `either` counter reaching the
    threshold and always flushing the parent (cards) first. When two
    batches have a FK dependency between them, tie their flush cadence
    together — don't let each grow and flush independently.

## Principles to keep enforcing in later phases

- **No AI/LLM anywhere in the core pipeline.** Import parsing, card
  normalization, comparison, pricing, refresh, metrics — all deterministic.
- **No fake success.** Health checks, refresh jobs, and provider status must
  reflect what actually happened, never a hardcoded "ok".
- **External services stay optional.** The app must fully start and be
  usable (manual imports at minimum) with every source adapter disabled.
- The comparison engine (`backend/app/comparison`, built in Phase 3) must
  stay a pure library with no FastAPI/SQLAlchemy-session/HTTP imports.

## Testing a change

```bash
cd ~/cardforge   # on the LXC
docker compose down
docker compose up -d --build
docker compose ps -a          # everything should be "Up"/"healthy", nothing stuck at "Created"
curl -s http://localhost:666/api/health/ready | jq
```

Backend: `cd backend && ruff check . && mypy app && pytest` — but `pytest`
needs `CARDFORGE_POSTGRES_DB=cardforge_test` and `CARDFORGE_REDIS_DB=1` set
first (see gotcha #13 and DEVELOPMENT.md "Tests"), or it refuses to start.
Frontend: `cd frontend && npm run lint && npm run build`
