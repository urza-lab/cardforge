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
| 4 | Deck/cube data model + manual text/JSON import, detail pages, interactive tables, CSV exports, shopping list |
| 5 | Moxfield/Archidekt public URL adapters, deck/cube CSV import, refresh system, scheduler, stale handling |
| 6 | Price cache, Scryfall/MTGJSON/manual providers, price profiles, budget filter (no direct Cardmarket API adapter — see "Documented default decisions") |
| 7 | Native dashboard, Grafana + Prometheus, collection leverage, backup docs |

Each phase is independently startable and testable; see the "Testing this
phase" note at the top of each phase's PR/commit.

Phase 4's row differs from the original plan in two ways worth calling out
(see "Documented default decisions" below): deck/cube manual import moved
here from Phase 5 (detail pages need something to show), and "budget
filter" moved to Phase 6 (it needs real price data that doesn't exist until
then — a filter with nothing to filter by isn't a feature, it's a stub).

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
- **One denormalized `scryfall_cards` table, not separate oracle/printing
  tables** (Phase 3): Scryfall's own "default_cards" bulk export is already
  one JSON object per printing with oracle-level fields (name, oracle_text,
  ...) repeated on every printing of that card — mirroring that shape
  directly means oracle-mode comparison (`GROUP BY oracle_id`) and
  printing-mode comparison (match the row's `id` exactly) both read from the
  same table with no join, at the cost of some duplicated text data Postgres
  doesn't mind.
- **A Scryfall bulk sync fully replaces the table, in one transaction**
  (Phase 3, see `app/source_adapters/scryfall.py`): the old rows are only
  deleted once the new file has downloaded and parsed successfully, and
  everything (delete + ~110k-row insert) commits atomically at the end. A
  failure at any point rolls back to the previous successful sync's data
  untouched — no partial mirror, no incremental upsert logic to get subtly
  wrong. At ~20s for the full `default_cards` file, incremental sync wasn't
  worth the complexity.
- **Sync status uses a 4-value subset (`NOT_STARTED`/`FETCHING`/`CURRENT`/
  `FAILED`) of SOURCE_ADAPTERS.md's full status vocabulary** (Phase 3) — the
  others (`AUTH_REQUIRED`, `RATE_LIMITED`, `SOURCE_CHANGED`, ...) describe
  failure modes a public-URL adapter (Phase 5) can hit, none of which apply
  to downloading one public, unauthenticated bulk-data file.
- **Scryfall auto-sync fires once, on first-ever start, and never
  auto-retries a failure** (Phase 3, `scryfall_service.maybe_auto_trigger_sync`,
  called from `app/main.py`'s lifespan): it only acts when status is
  `NOT_STARTED`. A `FAILED` sync does not retry itself on the next container
  restart — if something is persistently broken (no outbound network, DNS),
  auto-retrying every restart would just hammer Scryfall for no reason. The
  user re-triggers it manually from the System Status page instead.
- **Collection items are resolved against Scryfall automatically at
  import-confirm time** (Phase 3, `import_service.confirm_import` calls
  `scryfall_resolution.resolve_item` per new row) so freshly-imported cards
  are comparison-ready with no separate manual step — plus an explicit
  `POST /api/collections/{id}/resolve` to re-resolve a whole collection
  later (e.g. after the first-ever Scryfall sync finishes, for items
  imported before any sync had run).
- **Resolution is local-mirror-only, no REST fallback per unresolved card**
  (Phase 3): matching hundreds or thousands of collection rows by hitting
  `api.scryfall.com`'s single-card endpoint once per unresolved row would be
  exactly the uncoordinated-request pattern the bulk mirror exists to avoid
  (SOURCE_ADAPTERS.md "rate limits enforced centrally, not best effort"). A
  REST single-card lookup belongs to a future single-card detail UI that
  only ever looks up one card at a time — not built yet, so not added.
- **Printing-mode comparison never lets an unresolved card match anything**
  (Phase 3, `app/comparison/engine.py`): if a required or owned entry has no
  resolved `scryfall_card_id`, it's treated as unmatched in printing mode
  rather than falling back to a name-based guess — an unresolved row is not
  proof of owning (or needing) any *particular* printing, and printing mode
  exists specifically to answer that exact-printing question honestly (see
  design principle 2, "no fake success"). Oracle mode falls back to
  normalized-name matching instead, since "do you own a card with this
  name" is still a meaningful question without a resolved oracle_id.
- **Comparisons are ad-hoc and never persisted** (Phase 3,
  `app/services/comparison_service.py`): unlike collection import, running a
  comparison doesn't write anything to the database, so it skips the
  preview/confirm/abort ceremony IMPORT_FORMATS.md describes for imports —
  parse, resolve, compare, and respond in one request. The decklist side
  reuses Phase 2's `text_list`/`json`/`generic_csv` parsers (not
  `manabox_csv`, which is collection-export-shaped: condition/price/language
  columns a decklist wouldn't have).
- **User settings are a minimal 1:1 `user_settings` table**
  (`default_comparison_mode`, `preferred_currency`) rather than a generic
  key-value settings blob — two concrete, typed columns are simpler to
  validate and migrate than a JSON bag for the two settings Phase 3 actually
  needs. `preferred_currency` is stored (and shown in Settings) even though
  nothing reads it yet — pricing/budget display is Phase 6 — so the setting
  has one home from the start instead of being bolted on later.
- **Tests require `CARDFORGE_POSTGRES_DB` to look like a test database and
  `CARDFORGE_REDIS_DB` to be non-zero, enforced by a hard `pytest_configure`
  guard** (Phase 3, `backend/tests/conftest.py`): Phase 3 introduced two ways
  a test run could damage the real running app that Phase 2's tests couldn't
  — `scryfall_cards` now holds ~110k rows of real reference data a test's
  cleanup fixture deletes/repopulates, and Scryfall-sync tests enqueue real
  RQ jobs onto whatever Redis DB is configured, which (at index 0) is the
  same one the real `worker` container listens on. See DEVELOPMENT.md
  "Tests".
- **Manual deck/cube import moved from Phase 5 into Phase 4** (see
  `app/models/lists.py`, `app/parsers/list_text.py`,
  `app/services/list_import_service.py`): Phase 4's own deliverable ("deck/
  cube detail pages") needs decks/cubes to exist before there's anything to
  show a detail page for, and text/JSON manual import is buildable with
  infrastructure Phase 2/3 already proved out (the parser/preview/confirm
  pattern, Scryfall resolution). What actually stayed in Phase 5 is the part
  that name is really about: the Moxfield/Archidekt *public URL* adapters
  and the refresh/staleness system around them — plus CSV deck/cube import,
  cut for scope (see below), not because it needs anything Phase 5-specific.
- **`ListImport`/`ListImportRow` duplicate `Import`/`ImportRow`'s shape
  rather than generalizing one shared import pipeline for both collections
  and lists** (Phase 4): the two pipelines write structurally different
  target rows (`CollectionItem` has `condition`/price fields; `CardListItem`
  has `section`/`category`/`tags`), and a shared table would need a nullable
  `collection_id` *and* nullable `list_id` with an application-enforced
  "exactly one is set" invariant instead of the database enforcing it via
  `NOT NULL`. Keeping them separate costs some duplicated code but means a
  bug in one pipeline structurally cannot touch the other's data — see
  `app/models/lists.py` module docstring.
- **Deck/cube manual import supports text and JSON only, not CSV** (Phase
  4): those two formats carry `section`/`category`/`tags` losslessly (see
  IMPORT_FORMATS.md); doing the same for CSV would mean adding those as
  mappable columns to the generic-CSV column-mapping UI for a format
  (spreadsheet-shaped deck exports) that's less common than text or JSON
  decklists in practice. Deferred to Phase 5 rather than shipped without
  section/category support, which would silently lose data on import.
- **Text-list section headers persist across lines, not just the one line
  they're on** (Phase 4, `app/parsers/list_text.py`): a `Sideboard:` header
  followed by five card lines puts all five in the sideboard, not just an
  implicit "next line only" rule — matching how real decklist exports
  (Moxfield, Archidekt, MTGO) write multi-card sections, and matching
  IMPORT_FORMATS.md's own worked example (mainboard cards first, unheaded;
  special sections after). A quantity prefix is optional (defaults to 1),
  since the spec's own commander line (`Commander: Atraxa, Praetors'
  Voice`) has none.
- **Only `mainboard`/`commander`/`companion` sections count as "required"
  for list buildability/shopping-list purposes** (Phase 4,
  `app/services/comparison_service.py` `REQUIRED_LIST_SECTIONS`) —
  `sideboard`/`maybeboard`/`considering` are informational. README.md scopes
  CardForge around Commander decks and cubes, which don't have a
  constructed-format-style required sideboard.
- **A multi-list shopping list runs one `compare()` call over every list's
  combined requirements against one shared owned pool, not N independent
  per-list comparisons summed together** (Phase 4,
  `comparison_service.run_shopping_list`): summing independent "do you own
  this" answers would double-count a card two decks both want if you own
  only one copy. Feeding all requirements into a single call lets the
  engine's owned-pool decrement (`app/comparison/engine.py`) correctly
  award that one copy to only one of the two requirements.
- **"Interactive tables" means a small local `useSort` hook, not a table
  library** (Phase 4, `frontend/src/hooks/useSort.ts`) — consistent with the
  Phase 1 decision against a component framework; client-side sort over the
  row counts this app deals with (hundreds, not virtualized-grid territory)
  doesn't need one.
- **Card name display language: per-item by default, forceable to one
  language in Settings** (added during Phase 4, user-requested — see
  `app/services/display_name_service.py`): each collection/list item shows
  the card name in whatever language its own import data recorded (e.g.
  ManaBox's "Language" column) — not the language CardForge cross-verified
  against Scryfall (see the ManaBox `Language`-column reliability issue
  found during Phase 3 testing: that column was wrong for the large
  majority of a real test collection, but the user's ask here is
  specifically to trust it anyway for display, independent of whatever the
  "true" print language provably is). `UserSettings.card_name_language`
  (`null`/`"de"`/`"en"`) overrides that per-item default for every card at
  once when set. Either way, a card without a mirrored localized name for
  the target language falls back to its canonical English name — never a
  blank or an error.
- **Switched the Scryfall bulk mirror from `default_cards` to `all_cards`**
  to make the above possible: `default_cards` (Phase 3's original choice,
  see that phase's decisions above) omits a card's non-English printings
  entirely whenever an English printing of the same card exists, which left
  `printed_name` populated for only a handful of cards printed in just one
  non-English language. `all_cards` includes every language as its own row.
  Confirmed cost: real sync against api.scryfall.com went from ~110k rows/
  ~77MB/~20s (`default_cards`) to substantially more — see CLAUDE.md status
  for the actual numbers from the last real sync.
- **Moxfield/Archidekt adapters reuse `ParseResult`/`ParsedRow`
  (`app.parsers.common`), not SOURCE_ADAPTERS.md's aspirational
  `SourceAdapter`/`ParsedList`/`NormalizedList` types** (Phase 5,
  `app/source_adapters/moxfield.py`, `archidekt.py`): both APIs are
  real, verified-against-live-endpoint JSON fetchers whose output maps
  cleanly onto the exact same row shape the text/JSON/CSV parsers already
  produce, so `list_import_service._persist_preview` and `confirm_import`
  serve URL-sourced and file-sourced imports through one code path with no
  branching on origin. `app/source_adapters/common.py`'s `DeckFetchResult`
  (deck name + `ParseResult`) is the only new type introduced. Both real
  APIs 403 without a descriptive `User-Agent` (not `httpx`'s default) —
  confirmed against live `api.moxfield.com` and `archidekt.com/api/decks`.
- **SSRF guard resolves DNS and blocks by IP, not by hostname string
  matching, and follows redirects manually** (Phase 5,
  `app/security/ssrf_guard.py`): a hostname allowlist/blocklist alone can't
  stop a public hostname resolving to a private IP, and `httpx`'s
  `follow_redirects=True` would skip re-validation on each hop. Every
  outbound source-adapter request (initial fetch and each redirect) is
  checked individually; max 5 redirects. A TOCTOU/DNS-rebinding gap between
  the check and the actual connection is accepted as a tradeoff for a
  self-hosted hobby tool, documented in `SECURITY.md`, not solved with a
  pinned-IP `httpx` transport.
- **Deck/cube CSV import is its own parser
  (`app/parsers/list_csv.py`, `source_type: "csv"`), not a reuse of
  collection import's `generic_csv`/`manabox_csv`** (Phase 5): those two
  map onto `CollectionItem` (condition/purchase price, no section/category/
  tags concept); `list_csv.py` mirrors their tolerant header-detection/
  column-mapping mechanics but maps onto `CardListItem`'s shape instead
  (`section`/`category`/`tags`, no condition/price), via a new shared
  `app.parsers.common.map_list_row` helper (parallel to the existing
  `map_collection_row`). `parse_tags` (comma-separated string or JSON
  array) was factored out of `json_list.py` into `common.py` so both JSON
  and CSV list import share one implementation.
- **A list's refresh state (`FETCHING`/`CURRENT`/`FAILED`/`AUTH_REQUIRED`)
  is stored on `CardList`; staleness itself is computed on read, not
  stored** (Phase 5, `app/services/list_refresh_service.py`): a refresh
  *attempt* has a real outcome worth persisting (mirrors
  `ScryfallSyncStatus`'s FETCHING/CURRENT/FAILED state machine, `app/
  models/scryfall.py`), but "has it been too long since the last one"
  is a pure function of `last_refreshed_at` and current time
  (`is_stale()`, `STALE_AFTER = 7 days`, not user-configurable yet) — there
  is nothing to keep in sync by storing a derived boolean.
- **A refresh replaces a list's items wholesale (delete + re-run the
  normal preview/confirm pipeline with `skip_bad_rows=True`), not a
  field-by-field diff/upsert** (Phase 5, `list_refresh_service.run_refresh`):
  a refresh is unattended (no user reviewing a preview), and reusing
  `create_preview_from_url`/`confirm_import` means the refresh path is
  exercised by the exact same tested code as an initial URL import. If the
  freshly fetched content hashes identically to the last confirmed import
  (via the existing duplicate-detection hash), nothing is replaced at all —
  only `last_refreshed_at`/`refresh_status` update, since "checked, nothing
  changed" is still a real successful check (see "no fake success" above),
  not an excuse to skip recording it.
- **`run_refresh`'s outer exception handler marks `FAILED` and re-raises
  for any exception it didn't specifically anticipate**, not just the
  expected `AuthRequiredError`/`SourceFetchError`/`SsrfBlockedError` cases
  (Phase 5): found via a real bug during Phase 5 development — a worker
  container running stale code (see CLAUDE.md gotcha #16) crashed a refresh
  job outside any of the specific `except` clauses, and because
  `trigger_refresh`'s "already FETCHING" guard has no other way to clear
  that state, the affected list was permanently locked out of ever being
  refreshed again. The catch-all ensures any failure — anticipated or not —
  still flips `refresh_status` back to something `trigger_refresh` will
  accept a retry against.
- **The periodic staleness sweep is a plain `threading` loop inside the
  worker process, not RQ's own scheduler** (Phase 5,
  `app/workers/run_worker.py`): the installed `rq==2.1.0` has no
  repeating/cron job primitive (`with_scheduler=True` only covers one-off
  `enqueue_at`/`enqueue_in` calls) and no `rq-scheduler`/`rq.cron` package
  is installed. A self-perpetuating `enqueue_at` chain (each run schedules
  the next) was considered and rejected — it has no clean way to avoid
  spawning a duplicate chain on every worker restart without adding
  Redis-lock bookkeeping the sweep doesn't otherwise need. A daemon thread
  that sleeps and enqueues `check_stale_lists` every 6 hours is enough for
  a single-worker, single/few-user self-hosted tool, and dies cleanly with
  the process instead of leaving orphaned scheduled state in Redis.
- **`price_observations` is a latest-value cache, not a price-history
  table** (Phase 6, `app/models/pricing.py`) — same reasoning as the
  refresh system's stored-status-vs-computed-staleness split above: nothing
  today reads price *trends*, only "what does this cost right now," so
  each provider's sync replaces its own rows wholesale rather than
  appending to a growing series. See PRICING.md for the full design and the
  two real data-integrity bugs this required fixing (see also CLAUDE.md
  gotchas): MTGJSON uuids that alias to the same `scryfallId`, and a
  Scryfall-resync price-extraction batch that could flush before its
  corresponding card batch.
- **Scryfall's own price data piggybacks the existing card-mirror sync;
  MTGJSON gets its own separate sync job** (Phase 6): Scryfall's bulk
  `all_cards` file already includes a `prices` object per card, so
  extracting it costs nothing extra — no second download, no second
  FETCHING/CURRENT/FAILED state machine needed (it shares
  `ScryfallSyncState`). MTGJSON's price data lives in genuinely separate
  files or with a genuinely different ID space, so it gets its own
  `PriceSyncState` row/job/API (`POST /api/mtgjson/sync`) rather than being
  forced into the Scryfall sync's shape.
- **No direct Cardmarket API adapter** (Phase 6, despite
  ARCHITECTURE.md/README.md/SOURCE_ADAPTERS.md all originally listing
  Cardmarket as its own planned provider): Cardmarket's own API requires
  OAuth app registration/approval, real friction for a self-hosted hobby
  tool with no concrete need beyond "get some EUR prices." MTGJSON's
  `AllPricesToday.json` already relays real Cardmarket retail prices
  (sourced from Cardmarket itself) without that — see PRICING.md. A direct
  Cardmarket adapter remains a real possible future addition if MTGJSON's
  relay ever proves insufficient, not something ruled out permanently.
- **Oracle-mode pricing resolves the *cheapest* printing sharing an
  oracle_id, not a specific one** (Phase 6,
  `pricing_service.resolve_cheapest_price_for_oracle`): this follows
  oracle-mode comparison's own "any printing satisfies this" philosophy
  (`app/comparison/engine.py`) through to pricing — the realistic cost of
  closing an oracle-mode gap is whatever the cheapest legal printing costs,
  not whichever printing an import happened to resolve to. Not batched (one
  query per candidate printing) — acceptable at a self-hosted single-user
  tool's scale (dozens of missing cards × single-digit printings each), not
  something built for hundreds-of-oracle-groups-per-request scale that
  doesn't exist here.
- **The budget filter is a pure function over already-priced data
  (`app/pricing/budget.py`), not folded into the comparison engine itself**
  (Phase 6): keeps `app.comparison` free of any pricing concept (it stays a
  pure library per this doc's design principles above) while still getting
  the same "plain data in, plain data out" testability — `apply_budget`
  takes a list of `PricedMissingCard` and a budget, returns an allocation,
  nothing else. Greedy cheapest-first, not collection-leverage-aware
  (that's Phase 7's "which purchases unlock the most buildability" — a
  materially different, harder problem this doesn't attempt to solve yet).
- **Pricing a comparison/shopping-list result is opt-in via a
  `price_profile_id` query param, not computed automatically** (Phase 6,
  `app/schemas/lists.py` `ListComparisonResponse.priced_missing`/`budget`):
  pricing every missing card costs a real DB round trip per card (more for
  oracle mode's cheapest-printing search) — a plain buildability check
  that doesn't ask for pricing shouldn't pay for it.
- **No collection/list-wide total valuation feature** (Phase 6, deferred):
  would mean resolving a price for every item (thousands of round trips for
  a large real collection, see the 2,653-item one this project develops
  against) with no batch-pricing endpoint built. Shipping a feature that's
  slow or unbounded at real data scale is worse than not shipping it yet —
  see PRICING.md "Frontend".
- **Collection leverage lives in `app/comparison/leverage.py`, as a pure
  function extending `compare()`, not a DB-touching service** (Phase 7):
  "which purchase unlocks the most buildability" is answered by literally
  simulating ownership of each candidate card and re-running the existing
  pure `compare()` per list — reusing the same engine rather than inventing
  a parallel scoring model keeps the two mathematically consistent by
  construction (a card's leverage can never disagree with what a real
  comparison would show once bought). `app/metrics/dashboard_service.py`
  is the DB-touching orchestration layer that loads owned/required cards
  and calls it — same split as `app.services.comparison_service` versus
  the pure engine it calls.
- **The leverage metric is "lists newly fully buildable, then total
  coverage-percent gain," not price-aware on its own** (Phase 7): a card
  that single-handedly completes two decks ranks above one that nudges
  five decks' coverage a little, matching what a collector actually cares
  about ("what should I buy to finish a deck") more directly than a raw
  coverage-sum would. Not batched — one `compare()` call per (candidate,
  list) pair — which is fine at a self-hosted single-user tool's real
  scale (dozens of missing cards × a handful of lists) but would need
  real optimization work before it could handle hundreds of either.
- **The dashboard is one aggregate endpoint (`GET /api/dashboard`), not
  several the frontend assembles itself** (Phase 7,
  `app/metrics/dashboard_service.py`): collection stats, per-list
  buildability, sync status, and the leverage ranking all come from one
  response so the Dashboard page fires one request, not five-plus.
- **`/metrics` has no `/api` prefix and no auth** (Phase 7,
  `app/api/metrics.py`): Prometheus's own scrape-path convention is a bare
  `/metrics`, and `prometheus/prometheus.yml` is already written assuming
  that; it's also never exposed outside the Docker network in the shipped
  compose file (Prometheus reaches it at `backend:8000` directly, not
  through the nginx-fronted `:666` the rest of the app uses), so it
  doesn't need the same access story as the actual API. Values are
  computed fresh from the same tables `dashboard_service` reads on every
  scrape (a pull-based exporter, not counters incremented during request
  handling) — see PRICING.md-style "no fake success": nothing here is
  hardcoded or estimated.
- **A Grafana panel embedded in the CardForge Dashboard page, user-
  requested (post-Phase-7), uses Grafana's own "Public Dashboard" sharing
  rather than blanket anonymous access:** a new `cardforge_list_coverage_
  percent{list_id,list_name,list_type}` gauge (`app/metrics/
  prometheus_exporter.py`) feeds a dedicated Grafana dashboard/panel
  (`grafana/dashboards/cardforge-high-coverage.json`, table view sorted by
  coverage %, with a clickable data link back to each deck/cube's CardForge
  page). Presented as a real security fork to the user rather than assumed:
  `GF_AUTH_ANONYMOUS_ENABLED` would make *all* of Grafana's dashboards
  viewable without login; Grafana's built-in "Public Dashboards" feature
  (confirmed live on the pinned `grafana-oss:11.4.0` via its API) shares
  exactly one dashboard behind an unguessable token URL, leaving everything
  else password-protected — chosen as the narrower, equally-simple option.
  Given the whole stack is already only reachable on the user's own trusted
  network with no login on the main app either, the *marginal* risk was
  judged small either way, but there was no reason to pick the broader
  option when the narrower one costs the same. Public-dashboard shares have
  no file-based provisioning API in Grafana OSS (unlike datasources/
  dashboards, which do) — the share link is generated once via Grafana's
  own HTTP API (or its Share UI) and pasted into `UserSettings.
  grafana_embed_url` (Settings page), which the Dashboard page then iframes
  if set, or shows a setup hint if not. `GF_SECURITY_ALLOW_EMBEDDING=true`
  is required separately — Grafana denies all iframe framing by default
  regardless of the public-dashboard setting, a different, narrower "can
  this be framed at all" decision from "is login required." The embed being
  actually useful depends on the observability stack running, which is
  off by default (`profiles: ["observability"]`) — since the whole point of
  this feature is an always-there panel on the Dashboard page, not a
  once-in-a-while opt-in view, `COMPOSE_PROFILES=observability` in `.env`
  (documented in `.env.example` and README.md) starts it automatically on
  every `docker compose up` for a deployment that wants it, without
  changing the shipped default for anyone else cloning the repo. Combined
  with grafana/prometheus's existing `restart: unless-stopped`, once
  started this way they also come back on their own after a host/Docker
  reboot with no compose command needed at all.
- **The embed URL was first shipped as `http://<host>:3000/public-dashboards/
  ...` (Grafana's own separate host port) - changed to a same-origin
  `/grafana/public-dashboards/...` path after the user pointed out a
  browser iframe can't reach an internal Docker network hostname, and asked
  whether it could "stay on the docker network" instead of needing a second
  host:port.** It can't literally stay docker-internal (the iframe still
  renders in the user's own browser, which only ever sees published host
  ports), but the practical goal - not needing to know/expose a second port
  - is achievable by reverse-proxying Grafana under the app's own origin:
  `frontend/nginx.conf` gained a `/grafana/` location (same resolve-per-
  request pattern as `/api/`, see gotcha #26), and `GF_SERVER_ROOT_URL`/
  `GF_SERVER_SERVE_FROM_SUB_PATH` (removed earlier per gotcha #24, when no
  matching nginx location existed yet) were re-added now that one actually
  does. `grafana_embed_url` now only ever needs to be a path, not a full
  URL with its own host/port.
- **A second panel (real scatter plot: coverage % vs. real cost to
  complete) was added after the user asked, and confirmed real price data
  already exists to back it** (Phase 6's MTGJSON/Scryfall syncs - see
  PRICING.md). A new `cardforge_list_missing_cost{list_id,list_name,
  list_type,currency}` gauge feeds it, using the same "omit rather than
  show a partial number" rule as the coverage metric - a list only gets a
  value if every one of its missing cards actually resolved a real price.
  **A real, non-hypothetical performance bug was caught and fixed before
  shipping this**: the first implementation reused
  `pricing_service.resolve_cheapest_price_for_oracle` (built for, and fine
  at, a single list's own on-demand comparison page) for every list on
  every `/metrics` scrape - confirmed live to take minutes against the real
  collection's real decks, wildly unacceptable for a Prometheus scrape
  target hit every ~15s. Rewritten as a purpose-built batched version in
  `app.metrics.dashboard_service.compute_list_missing_cost` (2 queries
  total regardless of list/card count, instead of one query per missing
  card per provider) - confirmed live back down to the same ~0.6-0.8s the
  rest of `/metrics` already took. The `xychart` panel's own field-mapping
  transformations (`joinByField` + `seriesMapping: "auto"`) could only be
  verified as far as "the underlying query data reaches Grafana correctly
  and the dashboard JSON provisions without error" - the transformation
  chain and actual chart rendering happen client-side in the browser, which
  this session has no tool to drive (same limitation noted throughout for
  the CardForge frontend itself); treat the scatter plot as needing a
  first real look before trusting its axes are what they claim to be.
- **Found and fixed while wiring the embed above: Grafana's `GF_SERVER_
  ROOT_URL`/`GF_SERVER_SERVE_FROM_SUB_PATH` were pre-set (Phase 7) for a
  future nginx `/grafana/` reverse-proxy path that was never actually
  built** (`frontend/nginx.conf` has no such location - Grafana has only
  ever been reached directly on its own `GRAFANA_HOST_PORT`). With
  `serve_from_sub_path` on, Grafana 301-redirected every direct request
  (including the new embed's own URL) to that nonexistent sub-path, which
  then had nowhere to go. Removed both settings — Grafana now uses its own
  defaults, matching how it's actually deployed here.
- **Grafana/Prometheus data directories needed the same root-owned-
  bind-mount fix as `./data/secrets`/`./data/scryfall_cache`** (Phase 7,
  `backend/scripts/init_secrets.py`): `prom/prometheus` runs as a fixed
  65534:65534, `grafana/grafana-oss` as 472:0 — Docker still auto-creates
  `./data/prometheus`/`./data/grafana` as root on first start regardless of
  which non-root user eventually needs to write there, so `secrets-init`
  now chowns those too. `grafana_admin_password` specifically is owned by
  grafana's own uid (472), not the shared 1000:1000 the backend/worker-
  readable secrets use — see `SECRET_SPECS`' per-secret owner override,
  since nothing but the grafana container itself ever reads that file.
- **Popular-deck discovery (post-Phase-7, user-requested) is a local cache
  synced on demand, never a live query per browse request** (`app/models/
  discover.py` `PopularDeck`, `app/services/discover_service.py`
  `run_discovery_sync`): the same FETCHING/CURRENT/FAILED sync-job shape as
  Scryfall/MTGJSON, for the same reason — Moxfield's real search API
  rate-limited this project (HTTP 429) after a burst of unpaced requests
  during development, so hitting it live on every page view would be both
  slow for the user and unfriendly to the source's servers. Each source
  paces its own handful of requests with a fixed delay
  (`POPULAR_DECKS_REQUEST_DELAY_SECONDS` in each of `moxfield.py`/
  `archidekt.py`) rather than firing them all at once.
- **A second source (Archidekt) was added later, and an earlier "Archidekt
  needs auth" conclusion turned out to be wrong, not a hard fact:** the
  original discovery work only tried Archidekt's authenticated `/api/decks/
  v2/` endpoint, got a 401, and stopped there. The real public search API
  (`/api/decks/v3/`) was only found later by scraping archidekt.com's own
  search page HTML for embedded API paths — a reminder that a quick 401 on
  one guessed endpoint isn't proof a public API doesn't exist elsewhere.
  Each source is fully independent in `discover_service._SOURCES`: one
  source failing a sync (e.g. Moxfield rate-limiting again) doesn't lose or
  block the other's decks — `run_discovery_sync` only reports FAILED if
  every source failed that run, and records a partial-failure message in
  `error_message` otherwise rather than hiding it (still "no fake success":
  a real partial failure stays visible, it's just not conflated with a
  total outage).
- **Decks only, no cubes, in the popular-deck browser — a deliberate scope
  cut, not a gap nobody noticed:** neither Moxfield's nor Archidekt's public
  deck-search API has a cube format value, and no separate public
  cube-search endpoint was found for either. Presented as an explicit
  choice rather than assumed: build decks now with real verified data, or
  hold off building anything and research further, or ship cubes anyway
  with worse data quality. "Decks now" was chosen — see SOURCE_ADAPTERS.md
  for the paths not taken (a cube-search API that may not exist publicly on
  either site; a new, unverified CubeCobra adapter).
- **One-click "import" (single or bulk) reuses the existing URL-import
  pipeline wholesale — no new import/parsing logic was written for deck
  discovery at all:** a cached `PopularDeck.source_url` is a real deck URL
  on its own source, so "import this" is just `POST /api/lists` (create) →
  `POST /api/list-imports/preview-url` → `POST /api/list-imports/{id}/
  confirm` — the exact same three calls the "Import Lists → From a URL"
  flow already makes (Phase 5). Bulk import (checkbox-select + "select all",
  user-requested) is purely a frontend loop over that same three-call
  sequence per selected deck, sequential rather than parallel (keeps
  request pacing predictable and per-deck progress easy to show) — no
  backend endpoint or schema change was needed for it. The imported list
  also comes out with `source_url`/`source_type` set either way, so it's
  refreshable through the existing Phase 5 refresh system for free, with no
  discovery-specific code needed for that either.
- **EDHREC synthesized decks are a separate model, sync, and frontend tab
  from Moxfield/Archidekt discovery — not a third row in the same
  `PopularDeck` table, on purpose:** a `PopularDeck` row is always a real
  decklist someone else built, with a real URL that's independently
  refreshable; a `SynthesizedDeck` (`app/models/edhrec.py`) is computed by
  this app itself from EDHREC's real per-commander statistics (most-played
  cards per category, picked up to that commander's own real average
  card-type counts) - there's no author, no source decklist, and no URL to
  refresh from later (the decklist text is generated once at sync time and
  stored directly). Folding a fundamentally different kind of "deck" into
  the same list under a same-looking badge would blur a distinction users
  need to make correctly (would I actually build this, vs. does someone
  really play this) - presented as a real fork with real tradeoffs, user
  chose the separate tab over mixing sources.
- **EDHREC's page-scrape reuses the *upload* import entry point
  (`POST /api/list-imports/preview`), not the URL one:** Moxfield/Archidekt
  discovery imports work by handing the cached `source_url` straight to the
  existing `preview-url` endpoint, which fetches it again at import time.
  EDHREC has no analogous URL to fetch a decklist from — the deck was
  already synthesized and stored as plain text at sync time — so import
  just sends that stored text through the exact same upload path a manually
  pasted text list already uses, with zero new backend import/parsing code.
- **Periodic background sync for Scryfall/MTGJSON (user-requested,
  "wäre sowas nicht sinnvoll") reuses the exact same staleness-sweep shape
  as the list-refresh system** (`app/workers/run_worker.py`
  `_periodic_data_sync_loop` - a plain daemon thread with a sleep loop, same
  "no repeating-job support in rq==2.1.0" reasoning as the sweep it sits
  next to) rather than each provider's own bespoke scheduling. It calls
  each provider's existing `trigger_sync(db)` - the same function the
  manual "Sync now" button calls - so a tick landing while a sync is
  already `FETCHING` (started manually, by the other provider's tick, or a
  slow previous run) is rejected the same way a second manual click would
  be, not queued as a wasteful duplicate. Kept behind a real off switch
  (`CARDFORGE_PERIODIC_SYNC_ENABLED`, default on) for the same "external
  services stay optional" reasoning as everything else that makes outbound
  network calls on its own. **Building this surfaced a real
  `psycopg.errors.DuplicatePreparedStatement` bug** (see CLAUDE.md gotcha
  #28) that no earlier manual, spaced-out sync in this project's whole
  history had ever hit - only two syncs firing back-to-back did. Fixed at
  the engine level (`app/core/database.py`,
  `connect_args={"prepare_threshold": None}`), not by adding artificial
  spacing between the two triggers, since the same class of bug could
  recur from any future code path that fires multiple heavy batch-write
  jobs close together.
- **Bulk multi-URL deck import (Import Lists page, user-requested) reuses
  the same three-call pipeline per URL, sequentially - no new backend
  import path.** Each pasted URL gets its own auto-created `CardList`
  (placeholder name derived from the URL's own last path segment, since a
  list has to exist before `preview-url` can be called), then a real
  `PATCH /api/lists/{id}` rename to the source's own actual deck name once
  known. That rename endpoint, and exposing `DeckFetchResult.deck_name` on
  `ListImportPreviewResponse` at all, didn't exist before this - the value
  was already being fetched by `moxfield.py`/`archidekt.py` and silently
  discarded every single-URL import this whole time.
- **Bulk select-all delete/refresh on the Decks & Cubes overview
  (user-requested) has no confirmation dialog, matching the single-list
  delete button on the detail page** (`ListDetail.tsx`), which never had
  one either - added consistently with the existing convention rather than
  introducing a new interaction pattern only for the bulk case. Refresh
  only ever targets selected lists that actually have a `source_url` -
  silently skipping the rest rather than surfacing the expected `400
  NotUrlSourcedError` a manually-imported list would otherwise 400 on.
- **The color-identity filter is a subset match, not an exact match**
  (`app/services/discover_service.py` `list_popular_decks`): filtering by
  "WU" also returns a mono-W or mono-U deck, not only decks whose identity
  is *exactly* {W, U} — matching how deckbuilding actually works ("what
  can I build in these colors") rather than a literal string-equality
  filter almost nothing would pass.
- **The bracket filter was built despite real, checked-live sparse
  coverage (~15% of Archidekt decks, 0% of Moxfield decks - confirmed live
  before building), rather than skipped for "not enough data"** - the user
  explicitly chose to build it anyway once shown the real number, on the
  reasoning that a filter over incomplete-but-real data (decks without a
  bracket simply don't match, never fabricated one) still has genuine value
  for the ~15% it does cover, and costs nothing extra since Archidekt's
  real search API already returns `edhBracket` in the same response
  `fetch_popular_decks` already parses - see SOURCE_ADAPTERS.md.
- **Budget filtering on Discover Decks was scoped-but-not-built after the
  user asked specifically whether it was a RAM/resource constraint**: it
  isn't - a batched price lookup (the same pattern gotcha #27's fix
  established) would make the actual price *computation* cheap. The real
  constraint is external and structural: cached `PopularDeck` rows only
  ever hold search-result *metadata* (name/views/likes), never a deck's
  actual card list - getting that requires the same per-deck fetch used at
  import time, and there is no bulk "many decks' contents at once" endpoint
  on either Moxfield or Archidekt, only bulk *search*. Bulk-pricing all
  ~1,000 cached decks would mean ~1,000 additional individual HTTP requests
  to those sites' per-deck endpoints on top of what discovery sync already
  does - a real rate-limit/goodwill risk (Moxfield has already 429'd this
  project once at far lower volume), not a compute-resource one. Proposed
  instead, pending the user's direction: price a deck lazily the first time
  it's actually viewed/considered, caching the result, so budget-sortable
  coverage builds up organically without an eager bulk sweep.
- **Periodic background sync (user-requested) reuses each provider's own
  `trigger_sync(db)` instead of enqueueing the sync job directly** (see
  ARCHITECTURE.md's own entry above for the shape) - guarantees a tick that
  lands mid-sync is rejected the same way a second manual "Sync now" click
  would be, not queued as a duplicate. Real, unplanned discovery from
  building this: two large batch-write syncs firing back-to-back (which
  manual, human-paced clicking had never done before) surfaced a real
  `psycopg.errors.DuplicatePreparedStatement` bug - see CLAUDE.md gotcha
  #28 for the fix (disabling psycopg3 autoprepare at the engine level).
- **CubeCobra fills the cube-support gap this doc's "Documented default
  decisions" and SOURCE_ADAPTERS.md both used to describe as "not planned"**
  - the earlier conclusion (no public Moxfield cube-search API, a CubeCobra
  adapter would be "new, unverified work") wasn't wrong about Moxfield, but
  never actually verified CubeCobra itself; real research this time (reading
  CubeCobra's own open-source server code, the same technique that found
  Archidekt's real search API) found it has exactly what's needed: a real
  popularity-sorted search endpoint and a real per-cube CSV export. Kept as
  its own model/tab rather than merged into `PopularDeck`/Discover Decks,
  same "materially different shape" reasoning as EDHREC (a cube isn't a
  deck - card_count/tags instead of format/color-identity, and CubeCobra's
  only real popularity signal is likes, no separate view count) - but
  *unlike* EDHREC, CubeCobra cubes are real decklists (er, cube lists) with
  a real fetchable URL, so import reuses the URL-import pipeline (like
  Moxfield/Archidekt) rather than the file-upload one.
- **CubeCobra's CSV export needed one small adapter-local transform, not a
  new parser**: its real export has no quantity column at all (every card
  in a cube is implicitly one copy), but `app/parsers/list_csv.py` hard-
  requires a detected quantity column for any CSV source. Rather than
  changing that shared parser's behavior for every other CSV caller, the
  adapter injects a synthetic `Quantity=1` column into the fetched CSV text
  before handing it to the existing parser - the one CubeCobra-specific
  accommodation lives entirely in `app/source_adapters/cubecobra.py`.
- **A real 450-card CubeCobra cube import was the first import in this
  project's history to seriously expose a latent full-table-scan in name-
  only card resolution** (`app.services.scryfall_resolution.
  _match_oracle_id_by_name`'s `ILIKE` on the ~530k-row `scryfall_cards`
  table, confirmed via `EXPLAIN ANALYZE` at ~865ms worst case *per
  unmatched card*) - a singleton cube spanning far more distinct real sets
  than a typical ~100-card Commander deck sends far more cards through that
  fallback path. Fixed with a functional index on `lower(name)` - see
  CLAUDE.md gotcha #30 for the live verification (865ms sequential scan
  down to ~0.9ms index scan) and the declarative-model ordering gotcha it
  ran into along the way (`__table_args__` referencing `func.lower(col)`
  has to come after that column's own definition in the class body).
- **"Best coverage" (user-requested: rank real decks/cubes by how much of
  each you already own) is built as its own MTGJSON-precon source rather
  than added to `PopularDeck`/`PopularCube`/`SynthesizedDeck`** - those
  three only ever cache *metadata* (name/views/likes), never a deck's full
  card list, for the structural reason already documented above (no bulk
  "many decks' contents at once" endpoint on Moxfield/Archidekt/CubeCobra,
  only bulk search) - so ranking *them* by real coverage would mean a
  per-deck fetch at read time, the same rate-limit/goodwill risk already
  ruled out for lazy pricing. MTGJSON's bulk deck endpoints
  (`DeckList.json` + per-deck `decks/{fileName}.json`, see
  SOURCE_ADAPTERS.md) sidestep that entirely: each of the real 190
  official Commander precons' *complete* card list, with an exact
  `scryfallOracleId` per card, is fetched once at sync time and cached
  whole - so real buildability coverage against the user's collection can
  be computed live, for every cached deck, on every page load
  (`app.services.precon_service.list_precon_decks_with_coverage`, via the
  pure `app.comparison.engine.compare()` - no per-deck DB round-trip, let
  alone an external fetch). This is also why it's a materially different
  answer from EDHREC's synthesized decks (an *average* deck, not a real
  one MTGJSON/WotC actually printed) and gets its own "Best Coverage" tab
  rather than folding into either existing tab.
- **User pushed back on scope before approving the build**: 190 real
  decks was flagged as "eher spärlich" (rather sparse) and the user asked
  whether a bigger source existed (specifically: unofficial Moxfield/
  Archidekt scrape dumps) before committing to MTGJSON as the answer.
  Researched live rather than assumed: no Kaggle/HuggingFace dataset of
  either site's decks was found; mtgdecks.net's listing pages are
  scrapeable but individual deck pages are genuinely Cloudflare-protected
  (a real `_cf_chl_opt` JS challenge, confirmed live) - ruled out per this
  project's own rule against bypassing access controls, not a difficulty
  judgment call. cedh-decklist-database.com exists but is a small niche
  site, not investigated further once the Cloudflare finding made clear no
  *bigger* legitimate source was on the table. 190 real, exactly-resolved
  decks remains the best available option; reported both the positive and
  negative findings back before proceeding, rather than only the one that
  supported building the feature.
- **Import replays the CSV upload pipeline, like EDHREC's `deck_text` -
  not the URL-import pipeline CubeCobra/Moxfield/Archidekt use**: MTGJSON
  isn't a deck-hosting site with a per-deck URL to fetch-and-parse from at
  import time, so `PreconDeck.deck_text` is a ready-made CSV (`name,
  quantity,scryfall_id,section`, built with Python's `csv` module for safe
  quoting) sent through the existing `source_type="csv"` upload preview/
  confirm flow - verified live with a real 95-row, 0-error import of
  "Urza's Iron Alliance" (100 total cards; 95 distinct CSV lines because
  a few entries have quantity > 1).
- **Lazy pricing (user-requested, the deferred half of the bracket-filter
  batch above) prices exactly one `PopularDeck` at a time, on an explicit
  action, not eagerly for the whole cache** - the same structural
  constraint already documented for "best coverage" applies here too: a
  `PopularDeck` row only ever holds search-result metadata, so getting its
  real card list to price means a real per-deck fetch to Moxfield/
  Archidekt, and doing that for ~18,000 cached decks would be a genuine
  rate-limit/goodwill risk on sites this project doesn't control (Moxfield
  has already 429'd this project once at far lower volume - gotcha #23).
  `POST /api/discover/decks/{id}/price` reuses
  `adapter.fetch_and_parse(deck.source_url, user_agent)` - the exact same
  call the URL-import pipeline makes - runs the result through
  `app.comparison.engine.compare()` against the caller's collection, prices
  the missing cards via the existing `pricing_service.price_missing_cards`
  (Phase 6), and caches `coverage_percent`/`missing_cost`/
  `missing_cost_currency`/`priced_at` directly on the `PopularDeck` row, so
  a repeat page view costs nothing. Pricing is wiped back to null by the
  table's own periodic resync (the same delete-then-reinsert every
  `PopularDeck` row already gets) - accepted deliberately rather than
  engineered around (unlike gotcha #19's price-observation snapshot/
  restore): a cached deck price is a convenience value that's one click to
  recompute, not data a user would notice or mind losing across a resync.
- **Partial pricing is shown, not hidden, unlike `app.metrics.
  dashboard_service.compute_list_missing_cost`'s "omit the list entirely if
  any missing card lacks a price" rule** - that rule fits a metrics
  exporter scraped unattended, where a silently-partial number is worse
  than no number. Here, a human just clicked "price this deck" and is
  looking right at the result, so a partial total is still useful:
  `PopularDeck.unpriced_missing_count` tracks how many missing cards had no
  resolvable price at all, and the frontend shows it next to the total
  (e.g. "$4,227.26 (2 unpriced)") instead of a misleadingly complete-
  looking number or nothing.
- **`app.comparison.leverage`/`engine` were re-architected around a
  read-only, precomputed owned-pool once real data (590+ lists) exposed a
  real O(candidates x lists) blowup that "dozens of decks/cubes" never
  triggered** - see CLAUDE.md gotcha #32 for the full technical shape
  (`build_owned_pool`/`compare_pool` split, per-list-baseline dict lookups
  replacing a re-run `compare()` per candidate-list pair). This was a
  genuine site-down incident (dashboard 504s cascading into unrelated
  endpoints hanging too, since this project's single uvicorn process has
  no worker pool), not a preemptive optimization - the fix was driven
  entirely by live profiling (`cProfile`, manual timing checkpoints) after
  initial guesses about the bottleneck (first the DB query, then a naive
  reverse-index) both turned out insufficient once measured.
- **Server-side import tracking for Discover Cubes (`PopularCube.
  imported_list_id`/`import_error`/`import_attempted_at`) required
  switching `run_cube_discovery_sync` from plain delete-then-reinsert to a
  snapshot-before/restore-after pattern**, same shape as gotcha #19's
  price-observation preservation - without it, a routine resync would
  silently reset every cube's "already imported"/"failed" state, defeating
  the whole point of persisting it server-side instead of in React state.
- **A same-named `CardList` is not reliable proof it's the same real
  cube** - CubeCobra has no uniqueness guarantee on cube *names*, only on
  `external_id`. `import_popular_cube`'s "adopt an existing same-named
  list" logic only does so when the name is currently unambiguous (exactly
  one `PopularCube.external_id` has it); an ambiguous name gets its own
  disambiguated list (`f"{name} ({short_id})"`) instead of ever risking a
  wrong adoption - see CLAUDE.md gotcha #35 for the two real cross-linked
  rows this caught live and how they were corrected without deleting any
  real card data.

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
