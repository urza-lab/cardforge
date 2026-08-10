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
