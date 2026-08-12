# CardForge — CLAUDE.md

Context for Claude Code picking up this project. See `README.md` for the
product description and `ARCHITECTURE.md` for the full phase plan and
documented design decisions — read both before making changes.

## Status (updated after Phase 7 — the full 7-phase plan is now complete)

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

Phase 7 (native dashboard, Grafana + Prometheus, collection leverage,
backup docs) is **complete and verified end-to-end against real data**:
`GET /api/dashboard` was checked against the real 2,653-item collection
(distinct items/quantity/resolved count all correct) and against a real
Moxfield-imported deck (92 cards, 16% coverage, ranked collection-leverage
candidates matched hand-checked expectations — e.g. the 4 missing Forests
ranked above single-copy cards). The Prometheus exporter
(`GET /metrics`, no fake/hardcoded values) was verified scraped by a real
Prometheus container, and a real Grafana instance auto-provisioned the
datasource and the 8-panel "CardForge Overview" dashboard from the
`--profile observability` compose stack, confirmed via Grafana's own API
(datasource + dashboard both present, panels queryable). `scripts/backup.sh`
produced a real ~83MB dump of the live database (532,469 Scryfall
printings, 592,966 price observations, 2,653 collection items) that
restored cleanly into a disposable scratch database with identical row
counts across every major table — verified without ever touching the real
database with the restore path. Two real permission bugs
(root-owned `./data/prometheus`/`./data/grafana`, and
`grafana_admin_password` unreadable by grafana's own uid) were found and
fixed via live `--profile observability` starts, not assumed — see
gotcha #22. 262 backend tests pass (92% coverage); `ruff`, `mypy`, and the
frontend `lint`/`typecheck`/`build` are all clean. As with Phases 5/6, the
new frontend (Dashboard page) was verified via the built production bundle
serving real API data through the nginx proxy, not an actual browser
click-through — no browser-automation tool was available in this session.

This session separately found and fixed a real, long-standing bug
unrelated to Phase 7 itself: `ruff check .` had been failing in CI since
the Phase 2 push (FastAPI's `Depends()` pattern trips ruff's B008 rule,
and the repo never configured the standard exemption for it) — invisible
locally the whole time because `backend/Dockerfile` never copied
`pyproject.toml` into the image and `docker-compose.dev.yml` never
bind-mounted it either, so every local `ruff`/`mypy`/`pytest` run (in this
session and, it turns out, in every prior one) was silently running with
each tool's bare defaults instead of this repo's actual config. Fixed
separately from Phase 7 (commit `5a23da6`) — see gotcha #17 and
ARCHITECTURE.md.

**Post-Phase-7, user-requested:** a "Discover Decks" feature (browse real
popular Commander decks, one-click import) — the user asked after seeing
Binderbrew do something similar, comparing their collection against a pool
of decks/cubes rather than hunting for URLs one at a time. Researched live
before building anything: Moxfield's real public search API
(`/v2/decks/search`, sortable by real view/like counts) works and was
verified against live data; no public cube-search API was found on
Moxfield, and Archidekt's search API needs auth. Presented both findings
to the user, who chose decks-only rather than cubes-with-worse-data or
further research — see ARCHITECTURE.md "Documented default decisions" and
SOURCE_ADAPTERS.md. **Complete and verified end-to-end**: a real sync
landed 291 real popular decks (verified against Moxfield's live
`viewCount`/`likeCount`/`colorIdentity` fields) in ~6 seconds; a real
one-click import of the actual top-viewed cached deck
("Winota: Snowball Stax", 551,963 real views) through the exact API
sequence the frontend uses landed a real 303-card list, with
`source_url`/`source_type` set so it's refreshable through the existing
Phase 5 refresh system for free. 271 backend tests pass; `ruff`, `mypy`,
and the frontend `lint`/`typecheck`/`build` are all clean. A full `docker
compose down && up -d --build` cycle was verified afterward with the real
collection, the real Scryfall/MTGJSON caches, and the real 291-deck
discovery cache all intact.

**Discover Decks expanded, user-requested:** three follow-up ideas
("bulk-download Moxfield's/Archidekt's/EDHREC's popular decks?") were
researched live rather than assumed. Findings: Moxfield has no separate
public bulk-file endpoint (`/v2/decks/bulk`/`/v2/decks/export` are
auth-gated "export my own decks," not a public dataset) — the existing
paginated search already serves that role, so `POPULAR_DECKS_PAGES_PER_SORT`
was simply raised 2 → 5. Archidekt's original "needs auth" conclusion (from
the initial cubes/decks research) turned out to be based on trying only the
wrong endpoint — a real public search API was found this time
(`/api/decks/v3/`), and added as a second discovery source (see
SOURCE_ADAPTERS.md, ARCHITECTURE.md "Documented default decisions"). EDHREC
was investigated separately — see below, it needed a materially different
approach and its own decision point. **Complete and verified end-to-end**:
a real sync landed 693 real Moxfield decks + 300 real Archidekt decks (993
total, including a real 402k-view Archidekt deck) in ~23 seconds, both
sources merging into one cache with no cross-source interference; a real
one-click import of an Archidekt-discovered deck through the unchanged
URL-import pipeline landed 81/81 rows with 0 errors. A frontend-only bulk
"select decks, import all" action (checkbox + "select all" + sequential
per-deck progress) was added on top of the same three-call import sequence
— no backend changes needed for that part. 275 backend tests pass; `ruff`,
`mypy`, and the frontend `lint`/`build` are all clean.

**EDHREC synthesized decks, user-requested as the third of the same three
follow-up ideas above.** This one needed real design decisions, not just
another source in the same list — asked via AskUserQuestion rather than
assumed: EDHREC has no hosted decklists, only real per-commander card
statistics scraped from each page's embedded `__NEXT_DATA__` JSON (same
technique that found Archidekt's real search API). User chose scope
(top 100 commanders, the full real popularity ranking EDHREC exposes) and
UI placement (its own tab, not mixed into the Discover Decks list, since a
computed "average deck" is a materially different thing from a real
decklist someone built) - see ARCHITECTURE.md "Documented default
decisions" and SOURCE_ADAPTERS.md for the full real page-data shape found.
**Complete and verified end-to-end**: a real sync synthesized all 100 real
top commanders in ~88 seconds with zero per-commander failures (~600-700KB
HTML fetched per commander page, no rate-limiting seen); a real import of
the top-ranked synthesized deck ("The Ur-Dragon", 49,562 real EDHREC decks)
landed 100/100 rows with 0 parse errors through the *existing* upload-based
text-import endpoint (no new import/parsing code — EDHREC's synthesized
`deck_text` is just sent through the same path a manually pasted list
already uses, unlike Moxfield/Archidekt's URL-fetch-at-import path). 290
backend tests pass; `ruff`, `mypy`, and the frontend `lint`/`build` are all
clean.

**Grafana panel embed, the last of the same batch of user-requested ideas.**
A new `cardforge_list_coverage_percent` gauge plus a dedicated Grafana
dashboard (`grafana/dashboards/cardforge-high-coverage.json`) show
decks/cubes ranked by real buildability coverage, with clickable links back
into CardForge. Embedding it needed a real security decision, asked rather
than assumed — see ARCHITECTURE.md: Grafana's built-in "Public Dashboard"
sharing (verified live on the pinned `grafana-oss:11.4.0`) was chosen over
blanket anonymous access, since it scopes unauthenticated viewing to
exactly this one dashboard rather than all of Grafana, at the same
implementation cost. Building this also surfaced and fixed a real
pre-existing bug from Phase 7 (gotcha #24): a `/grafana/` sub-path redirect
config for a reverse-proxy path that was never actually built was silently
breaking direct Grafana access this whole time. **Complete and verified
end-to-end**: the real metric was confirmed scraped by Prometheus with real
coverage numbers for the user's actual decks; a real Public Dashboard share
was created via Grafana's API and confirmed to return real, correctly
labeled panel data over an unauthenticated request; the resulting URL was
saved through `PUT /api/settings` exactly as the Settings page would. 294
backend tests pass; `ruff`, `mypy`, and the frontend `lint`/`build` are all
clean.

**Post-launch fixes and follow-ups, user-requested after using the app for
real.** A real production outage (site-wide 502s) led to gotcha #26 (nginx
caching a stale backend IP) and its own fix/commit. Separately, five more
small user-requested items landed together: (1) the Grafana embed URL was
made same-origin (`/grafana/...` through a new nginx proxy location)
instead of needing a separate host:port, after the user asked whether it
could "stay on the docker network" — see gotcha #24's sequel in
ARCHITECTURE.md; (2) a second Grafana panel (real scatter plot: coverage %
vs. real cost-to-complete) was added after the user asked whether reliable
price data existed to back it (yes — Phase 6's real MTGJSON/Scryfall sync
data) — building this caught and fixed a real, non-hypothetical performance
bug (gotcha #27) before it shipped, not after; (3) a `PATCH /api/lists/
{id}` rename endpoint was added, and `deck_name` (previously fetched and
silently discarded on every Moxfield/Archidekt URL import) is now exposed
on the preview response; (4) the Import Lists page gained bulk multi-URL
import (paste several deck URLs, each becomes its own auto-named list); (5)
the Decks & Cubes overview gained select-all with bulk delete/refresh.
**Complete and verified end-to-end**: a real Archidekt URL and a real
Moxfield URL were both bulk-imported and auto-renamed to their real deck
names (81 and 92 real cards respectively) through the exact API sequence
the frontend uses; a real bulk refresh and real bulk delete were both run
against real lists afterward. 301 backend tests pass; `ruff`, `mypy`, and
the frontend `lint`/`build` are all clean.

**A further seven-part user request, answered/built one at a time rather
than assumed as a single batch.** (1) Automatic periodic background sync
for Scryfall/MTGJSON, user-asked ("wäre sowas nicht sinnvoll") - built as a
plain daemon thread (`app/workers/run_worker.py`
`_periodic_data_sync_loop`), same shape as the existing staleness sweep,
reusing each provider's own `trigger_sync` so a tick during an in-progress
sync is rejected the same way a second manual click would be. Off switch
kept (`CARDFORGE_PERIODIC_SYNC_ENABLED`, default on). Real bug found and
fixed building this: two large syncs firing back-to-back (something manual
clicking had never done) hit a real `psycopg.errors.
DuplicatePreparedStatement` - fixed at the engine level (gotcha #28).
(2) "Last updated" timestamp added to the Prices page (data already
existed server-side, just wasn't rendered). (3) Manual sync button
confirmed already present, no change needed. (4) Real research (not
assumption) into direct Cardmarket API access for condition/language/
seller filtering: Cardmarket's own help page states outright that new API
applications aren't being accepted at all right now - stronger and more
current than the original Phase 6 "real friction" reasoning, confirmed
live rather than re-guessed. (5) Real research into bulk-downloading
*all* Moxfield/Archidekt decks for a background "commander deck base":
Moxfield hard-caps at 10,000 results per sort (confirmed live - page
100/100 real, page 101 empty); Archidekt has no found ceiling (real,
distinct decks still returned 600,000 decks deep) but starts timing out
past ~50,000. Both pools were scaled up substantially anyway (Moxfield
5→50 pages/sort, Archidekt 5→200 pages) since a bigger *browse* pool is
straightforwardly valuable - but real "automatic coverage ranking across
thousands of uncompared decks" would need fetching each deck's actual card
list (not just search metadata), a materially bigger, rate-limit-risky
feature not built here. (6) Bracket/budget filters on Discover Decks -
real data check done (only ~15% of Archidekt decks have a bracket set at
all), scope not yet decided with the user. (7) Real research into cube-
list sources found CubeCobra has exactly what's needed - see the dedicated
paragraph below, since it became its own real feature, not just a finding.
262 → 301 → 318 backend tests across this whole batch; `ruff`/`mypy`/
frontend `lint`+`build` clean throughout.

**CubeCobra "Discover Cubes," the seventh item above, once research showed
it was real and buildable.** CubeCobra is open source - its real routes
were found by reading the actual server source (same technique that found
Archidekt's real search API), then verified live: a real popularity-sorted
(`likeCount`) cube search with DynamoDB cursor pagination, and a real per-
cube CSV export needing zero new parsing code (fed through the *existing*
deck/cube CSV parser via an explicit column mapping, plus one small
adapter-local fix - injecting a synthetic Quantity=1 column, since cubes
have no quantity concept and the shared parser hard-requires one). Kept as
its own model/tab (`PopularCube`, `frontend/src/pages/DiscoverCubes.tsx`),
same "materially different shape" reasoning as EDHREC, but *unlike* EDHREC
it's a real fetchable URL so import reuses the URL-import pipeline like
Moxfield/Archidekt. **Complete and verified end-to-end, including two more
real bugs found live under real load, not hypothetical**: a real sync
cached 1,419 real cubes (~75s); a real import of "The Pauper Cube" (2,270
real likes, 450 real cards) landed 450/450 resolved with 0 errors - but
getting there surfaced (a) a confusing multi-minute hang that turned out to
be a coincidental periodic-sync lock wait, not a real bug (gotcha #29), and
(b) a genuine full-table-scan in name-only card resolution that no import
in this project's history had been big/varied enough to hit hard before
(gotcha #30, fixed with a functional index, verified via `EXPLAIN ANALYZE`:
~865ms sequential scan down to ~0.9ms). 318 backend tests pass; `ruff`,
`mypy`, and the frontend `lint`/`build` are all clean.

**Bracket filter on Discover Decks, decided after showing the user the real
coverage number rather than assuming.** Live-checked before building: only
~15% of real Archidekt decks have a bracket set at all, Moxfield has no
such field. User chose to build it anyway - real WotC Commander Bracket
data (1-5) Archidekt's search API already returns for free, a deck without
one is simply excluded rather than shown with a fabricated value. Budget
filtering (the other half of the same original ask) was scoped but not
built: the user specifically asked whether it was a RAM/resource
constraint, and it isn't - the real limit is that cached decks only ever
hold search-result metadata, never a full card list, so pricing every
cached deck would mean one additional per-deck fetch to Moxfield/Archidekt
*each* (a real rate-limit risk on servers CardForge doesn't control), not
a compute problem. A lazy-price-on-view approach was proposed instead,
pending direction.

Verifying this against real data (a real resync at the now much bigger
pool sizes) hit a second real bug: the sync's `job_timeout` (900s) turned
out not to be enough - the first real attempt at the enlarged pool sizes
got killed by RQ's own `JobTimeoutException` with *nothing* committed,
even though isolated per-request timing samples of both Moxfield and
Archidekt during the same investigation showed nowhere near that slow.
Root cause wasn't conclusively pinned down (a real sync immediately after
doubling the timeout to 1800s completed in ~6.3 minutes, comfortably inside
the *original* 900s window - the first attempt looks like a one-off
slowdown, not a systematic issue) but the timeout was still doubled rather
than left at a value already shown live to be insufficient once. That real
resync landed 18,312 real decks (up from 993); the bracket filter was then
confirmed live against that real data - 3,216 of 18,312 decks (~17.6%,
consistent with the earlier smaller-sample estimate) have a real bracket
set, and `?bracket=3` correctly returns only those. 319 backend tests
pass; `ruff`, `mypy`, and the frontend `lint`/`build` are all clean.

**"Best Coverage" (MTGJSON precon decks), the third of a four-part
follow-up request, plus two things answered directly.** The user asked
(1) to commit/push the CubeCobra+bracket-filter batch above (done, commit
`c82547b`), (2) for lazy pricing (deferred - not built yet, see below),
(3) to research and, if viable, build a "best coverage" feature ranking
real decks/cubes by how much of each is already owned, and (4) why
Archidekt's "likes" column always shows 0. (4) was a quick live check, not
a bug: Archidekt's real deck-search API response has no likes/points/
favorites field at all (full key list confirmed) - `like_count=0` is a
deliberate honest choice, not fabrication. For (3), research found
MTGJSON's bulk deck endpoints (`DeckList.json` + per-deck fetch) expose
190 real official Commander precons with each card's exact
`scryfallOracleId` already resolved - the only real source found where a
deck's *complete* card list is available without a per-deck fetch to a
rate-limit-sensitive site, making live coverage computation (no cached,
staleness-prone percentage) actually cheap. Presented to the user before
building; the user pushed back that 190 was sparse and asked about bigger
unofficial Moxfield/Archidekt dumps - researched live (Kaggle/HuggingFace:
none found; mtgdecks.net: real Cloudflare JS challenge on deck pages,
ruled out per this project's access-control rule; cedh-decklist-
database.com: a small niche site, not pursued) and reported back that no
bigger legitimate source exists before proceeding with MTGJSON as planned.
**Complete and verified end-to-end**: a real sync landed all 190 real
Commander precons in ~2 minutes with 0 fetch errors; a real coverage-
ranked query against the user's actual 2,653-card collection returned
plausible numbers (13-33% for the top 10, none fully buildable, as
expected for decks with no overlap-by-design with an existing collection);
a real one-click import of the top-ranked deck ("Urza's Iron Alliance",
100 real cards) landed 95/95 CSV rows with 0 errors through the existing
upload pipeline (unlike Moxfield/Archidekt/CubeCobra, which use the
URL-import pipeline instead - MTGJSON has no per-deck URL to fetch from).
334 backend tests pass; `ruff`, `mypy`, and the frontend `lint`/`build`
are all clean.

**Lazy pricing, item (2) of the same four-part request, closing it out.**
`POST /api/discover/decks/{id}/price` prices exactly one cached
`PopularDeck` on an explicit "Price this deck" click - not the whole
~18,000-deck cache eagerly, for the same real reason budget filtering on
Discover Decks was scoped out earlier: a `PopularDeck` row only ever holds
search-result metadata, so getting an actual card list to price means a
real per-deck fetch to Moxfield/Archidekt, and doing that automatically
for every cached deck would be a real rate-limit risk (gotcha #23 already
burned this project once). Reuses the exact same `fetch_and_parse` call
the URL-import pipeline makes, runs it through the existing comparison
engine and Phase 6 pricing service, and caches
`coverage_percent`/`missing_cost`/`unpriced_missing_count`/`priced_at`
directly on the row so a repeat view is free - cleared again by the
table's own periodic resync (accepted on purpose: a convenience value,
one click to recompute, not data worth engineering a snapshot/restore
around the way gotcha #19's price observations were). Unlike the
Prometheus-exporter cost rollup (which omits a list entirely if any
missing card lacks a price), a partial total is still shown here with
`unpriced_missing_count` alongside it - a human just clicked the button
and is looking at the result, so a partial real number beats no number.
**Complete and verified end-to-end**: a real price request against
"Winota: Snowball Stax" (Moxfield, 552,130 real views) returned real
coverage (5.73%) and a real total ($4,227.26 USD, 0 unpriced) computed
from the user's actual collection and real MTGJSON/Scryfall price data;
a repeat `GET /api/discover/decks` showed the identical cached values with
no re-fetch; the cached price survived a full `docker compose up -d
--build` cycle. 343 backend tests pass; `ruff`, `mypy`, and the frontend
`lint`/`build` are all clean.

**Discover Cubes: server-side import tracking, retry/retry-all, and a real
production performance incident, all in one user-requested batch.** The
user asked for Discover Cubes to (1) keep showing "View list" for an
already-imported cube after a resync instead of reverting to "Import", (2)
mark failed imports and offer a retry button plus a "retry all failed"
action with a count and an ETA, and (3) investigated a real bug they'd
hit: some cubes came back empty with no source recorded after a bulk
import. Building this replaced the frontend's old 3-call client-
orchestrated import (`create list` → `preview-url` → `confirm`, with no
persisted outcome) with one backend endpoint (`POST /api/cube-discover/
cubes/{id}/import`) that does the same sequence but persists the result
directly on the `PopularCube` row (`imported_list_id`, `import_error`,
`import_attempted_at` - new columns, `ForeignKey(..., ondelete="SET
NULL")` so deleting the list reverts the cube to "not imported" rather
than a dead link) - a page reload or a later resync no longer loses
"already imported"/"failed, retry" state, since `run_cube_discovery_sync`
now snapshots and restores these three columns across its delete-then-
reinsert (same pattern as gotcha #19). Investigating item (3) found the
real root cause directly: a failed import used to leave its already-
created, now-orphaned empty `CardList` behind - fixed by deleting it on
any failure after creation. Two smaller, related things landed in the same
batch: real CubeCobra quality signals beyond `likeCount` (`numDecks` -
how many real decks have been built from a cube, and `dateLastUpdated`)
were added as columns/sort options after checking what CubeCobra's search
response actually exposes (no comment count or star rating exists in that
payload, confirmed live); and "Decks & Cubes" (`Lists.tsx`) plus the
Dashboard's own list table both gained sortable columns, including
sorting by coverage % (reusing `GET /api/dashboard`'s already-computed
buildability numbers rather than a second comparison call).

Verifying this at real scale turned into a genuine production incident and
its resolution, not just a feature ship. The user first reported the
Dashboard hanging (`HTTP 504`) - live investigation traced this to a real
bulk import they'd previously run (588 cubes, "select all") having pushed
the collection to 590 lists, which exposed three latent O(n) performance
bugs that "a household's dozen or so decks" had never triggered before
(see gotchas #32 and #33 for the full technical detail and fix). With the
site back up, the user asked to actually run the full 808-cube import (the
subset not already covered) as a real load test, explicitly to check for
CubeCobra rate-limiting and confirm no duplicate lists would result - **do
this only after checking**: 808 sequential real fetches to a third party
is exactly the kind of thing gotcha #23 warned about, so this was proposed
as a smaller sample first, and only run at full scale once the user
confirmed pacing would match what the original (already rate-limit-safe)
bulk import had used. Result: **0 real CubeCobra rate-limiting across all
808 real fetches** - every failure encountered was either this project's
own infrastructure (two brief, self-inflicted `nginx` 502 bursts, each
exactly coincident with a `docker compose up --build` run *during* the
live test - not a real bug, just bad timing overlapping deploys with the
test) or a real, fixable bug in this project's own code (gotchas #34 and
#35, both found and fixed live because a load test at this scale was the
first thing ever big/varied enough to hit them). Final state, verified
live: 1,297 real lists (802 pre-existing + 715 real cubes now correctly
tracked as imported, up from 580 before this batch - the 10 empty
orphaned lists from before this fix were deleted, and the two real
`imported_list_id` cross-links from gotcha #35 were corrected without
deleting any real card data, per the user's explicit "keep the real
lists, just fix duplicates" instruction), `GET /api/dashboard` at ~6-7s
against that real, now-larger dataset (down from an unbounded hang), zero
remaining `imported_list_id` collisions. 357 backend tests pass; `ruff`,
`mypy`, and the frontend `lint`/`build` are all clean.

Repo: `https://github.com/urza-lab/cardforge` (public). Tags `v0.1.0-phase1`
through `v0.1.3-phase1` mark the incremental Phase 1 fixes described below.
The LXC has its own push access — SSH deploy key
(`~/.ssh/cardforge_deploy`, write access, scoped to this one repo only),
remote set to `git@github.com:urza-lab/cardforge.git`. No separate `gh` CLI
install on the LXC.

**All 7 planned phases are now complete.** See `ARCHITECTURE.md` for the
full phase plan and "Documented default decisions" for the choices made
along the way (default-user bootstrap, `/collections/default`,
enum-as-VARCHAR, import preview persistence, duplicate-import flagging, JSON
collection import, the single denormalized `scryfall_cards` table,
resolution matching priority, ad-hoc non-persisted comparisons, minimal
`user_settings` table, the separate list-import pipeline, text-list section
semantics, multi-list shopping-list pooling, the Phase 5/6/7 decisions
above). Real possible future work, none of it scheduled: a direct
Cardmarket API adapter (PRICING.md), a batched pricing endpoint enabling
collection/list-wide total valuation (PRICING.md), splitting the refresh
system's coarse `FAILED` status into the finer-grained ones
SOURCE_ADAPTERS.md originally sketched, and a price-per-dollar-aware
variant of collection leverage (ARCHITECTURE.md).

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
21. **`docker compose down` (no `--profile` flag) does not stop containers
    started under a named profile, even though `down` normally tears down
    "everything"** (found in Phase 7): `prometheus`/`grafana` were left
    running (and holding the shared network open — `down` then failed with
    "Network cardforge_default Resource is still in use") after a plain
    `docker compose down`, because compose only resolves the *default*
    profile set (none active) unless told otherwise, the same as `up`. Use
    `docker compose --profile observability down` (matching whatever
    `--profile` flag started them) to actually stop profile-gated services
    — `down` isn't an exception to the profile-scoping rule `up` follows.
22. **The optional observability stack (`--profile observability`) needed
    the same root-owned-bind-mount treatment as `./data/secrets`/
    `./data/scryfall_cache`, for two more directories and one more
    secret** (Phase 7): `./data/prometheus` (prom/prometheus runs as fixed
    uid 65534) and `./data/grafana` (grafana/grafana-oss runs as fixed uid
    472, group 0) are both auto-created root-owned by Docker on first
    start, same as ever — `secrets-init` now chowns both (see
    `backend/scripts/init_secrets.py`). Separately, `grafana_admin_password`
    itself (already 0600, already owned by uid 1000 for the
    backend/worker-readable secrets) was unreadable by the grafana
    container specifically, since grafana runs as uid 472, not 1000 — fixed
    by adding a per-secret owner override (`SECRET_SPECS`' third tuple
    element) so a secret only one *other*, non-cardforge service reads can
    be owned by that service's own uid instead of the shared default.
    Symptom both times was a container stuck `Restarting (1)` in `docker
    compose ps` with a permission-denied line in its logs — treat that
    combination as "check who owns the bind-mounted path vs. which uid the
    image actually runs as" before assuming anything more exotic.
23. **Moxfield's public search API (`/v2/decks/search`) really does rate-
    limit (HTTP 429) after a burst of unpaced requests** (found live during
    research for the post-Phase-7 discovery feature, testing ~8 different
    `sortType` values back-to-back with no delay). Any future code hitting
    this endpoint (or the per-deck `/v2/decks/all/{id}` one) needs pacing
    between requests — see `POPULAR_DECKS_REQUEST_DELAY_SECONDS` in
    `app/source_adapters/moxfield.py` for the pattern already in place.
    Also confirmed live: `sortType` only accepts `views`/`likes`/`created`/
    `updated`/`name` (not `trending`/`popularity`/`hot`/`velocity`/
    `random`), and there is no `cube` value for `fmt` — don't re-guess
    these; see SOURCE_ADAPTERS.md for what's actually confirmed to work.
24. **Grafana's `GF_SERVER_SERVE_FROM_SUB_PATH=true` + a `/grafana/`
    `GF_SERVER_ROOT_URL` (set in Phase 7 for a reverse-proxy path that was
    never actually built) 301-redirects *every* direct request to that
    nonexistent sub-path** (found while wiring the Grafana embed feature
    post-Phase-7) — including the embed's own URL, which then 404'd since
    `frontend/nginx.conf` has no `/grafana/` location and never did. Fixed
    by removing both settings; Grafana is only ever reached directly on its
    own `GRAFANA_HOST_PORT` in this project, not proxied, so it needs its
    own defaults. If a real `/grafana/` nginx proxy is ever added later,
    both settings need to come back together with the matching nginx
    location — don't re-add one without the other.
25. **Grafana OSS's "Public Dashboard" share links have no file-based
    provisioning** (unlike datasources/dashboards, which do — see
    `grafana/provisioning/`) — only its HTTP API or Share UI can create one,
    and the resulting access token is stored in Grafana's own database
    (persists across container recreates via the `./data/grafana`
    bind-mount, confirmed live). Don't try to provision one via YAML; it has
    to be a one-time API call or UI action, with the resulting URL then
    handed to the app (here: pasted into Settings → `grafana_embed_url`).
26. **`frontend/nginx.conf`'s `/api/` proxy resolved `backend`'s IP once at
    nginx startup and cached it forever — recreating the `backend` container
    without also restarting/rebuilding `frontend` made every `/api/*`
    request 502 with "connect() failed (111: Connection refused)"** (a real
    production outage during this session: `backend` had been rebuilt
    several times for testing while `frontend` kept running, so nginx was
    still holding backend's *previous* container IP). Fixed with Docker's
    embedded DNS resolver (`resolver 127.0.0.11 valid=10s;`) plus a
    `set $backend_upstream ...; proxy_pass $backend_upstream$request_uri;`
    instead of a bare `proxy_pass http://backend:8000/api/;` — this forces
    nginx to re-resolve `backend` on every request instead of once at
    startup. **Gotcha within the gotcha, also found live**: nginx only does
    its usual "replace the matched location prefix with the proxy_pass URI"
    rewriting when `proxy_pass`'s target is a static string — the moment a
    variable is involved (needed for the resolver fix above), that
    rewriting silently stops happening and nginx appends *nothing* from the
    original request to the proxied URL (every request landed on the
    backend as a bare `/api/`, path completely dropped, surfacing as a wrong
    307 redirect). `$request_uri` has to be appended explicitly whenever
    `proxy_pass` uses a variable — don't reintroduce a bare `proxy_pass
    $var;` without it. Verified live both ways: with the fix, recreating
    `backend` alone (`docker compose up -d --force-recreate backend`, no
    touching `frontend`) kept `/api/*` working end-to-end once backend
    became healthy again.
27. **A per-card DB-lookup pricing helper built for one list's own on-demand
    comparison page (`pricing_service.resolve_cheapest_price_for_oracle`,
    one query per candidate printing per missing card) is *minutes* slow
    when reused for every list on every `/metrics` scrape** (found live
    while adding the `cardforge_list_missing_cost` gauge for a Grafana
    scatter plot, post-Phase-7) — fine at its original, small-N, on-demand
    scale, wildly wrong for a Prometheus-scraped endpoint hit every ~15s.
    `app.metrics.dashboard_service.compute_list_missing_cost` was rewritten
    as its own batched version instead (2 queries total for every list's
    every missing card combined, not one query per card per provider) —
    back down to the same ~0.6-0.8s the rest of `/metrics` already took.
    Treat "how many DB round-trips does this do, and how often does the
    *new* caller actually invoke it" as something to check explicitly
    before reusing an existing service function in a scrape-frequency
    (or otherwise hot/frequent) code path — a helper's existing docstring
    saying "not batched, fine at this scale" is a warning label, not
    boilerplate; a new caller can invalidate the "this scale" part.
28. **Two large batch-INSERT syncs (Scryfall then MTGJSON) run back-to-back
    in the same worker process can hit `psycopg.errors.
    DuplicatePreparedStatement: prepared statement "_pg3_0" already
    exists`** (found live adding periodic background sync, post-Phase-7) —
    a pooled SQLAlchemy connection reused within milliseconds of its
    previous large `executemany` still had a server-side prepared statement
    active, and psycopg3's next auto-generated statement name collided with
    it. Every *manual*, spaced-out sync earlier in this project's life
    never hit this — only two syncs firing back-to-back (as the new
    periodic sync loop does) did, since real-world gaps between manual
    triggers apparently gave the pool time to avoid the collision. Fixed by
    disabling psycopg3's autoprepare entirely
    (`connect_args={"prepare_threshold": None}` in
    `app.core.database.get_engine`) — verified live both ways: reproduced
    the exact failure once (trigger Scryfall, wait for CURRENT, immediately
    trigger MTGJSON), confirmed the fix resolves it the same way, then
    confirmed a real periodic-loop tick (both syncs enqueued within the
    same tick) completes clean with the fix in place. Any future code that
    fires multiple heavy batch-write jobs close together in the same
    process should assume this class of bug is possible, not assume
    connection pooling "just works" for that access pattern.
29. **Restarting the `worker` container resets the periodic-sync thread's
    startup delay, not just the staleness sweep's** (found live testing
    CubeCobra import, post-Phase-7) — every `docker compose restart worker`
    during active development (needed after any code change the worker
    executes, see gotcha #18) re-arms `PERIODIC_SYNC_STARTUP_DELAY_SECONDS`
    (60s) from scratch, so a real Scryfall+MTGJSON sync can kick off
    mid-session with no warning, ~60s after any worker restart, regardless
    of the real 24h interval setting. This isn't a bug to fix (the
    behavior is correct - a fresh worker process legitimately doesn't know
    how long it's been since the last real sync), but it did cause a real,
    confusing multi-minute hang during this session: a large (450-card)
    CubeCobra import's `confirm` got stuck behind Postgres locks held by a
    coincidental Scryfall resync that fired ~60s after an unrelated worker
    restart. Diagnosed via `pg_stat_activity`/`pg_blocking_pids` (`SELECT
    a.pid, a.state, pg_blocking_pids(a.pid) FROM pg_stat_activity a WHERE
    state != 'idle'`) - the import itself wasn't broken, it was just
    waiting on a real, legitimate, but badly-timed sync. Expect this
    combination (worker restart mid-dev-session -> real sync ~60s later)
    and don't mistake the resulting lock wait for a new bug without
    checking `pg_stat_activity` first.
30. **`ScryfallCard.name.ilike(name)` with no wildcards forces a full
    sequential scan of all ~530k rows on every unmatched name** (found live
    during the same CubeCobra import hang above, via `EXPLAIN ANALYZE` -
    confirmed ~865ms worst case per call) — a plain B-tree index on `name`
    can't accelerate a case-insensitive comparison; Postgres needs a
    functional index on `lower(name)` for that specifically. This had
    always been a latent risk (`app.services.scryfall_resolution.
    _match_oracle_id_by_name`, the fallback for any card whose set_code +
    collector_number doesn't exactly match), but no prior real import in
    this project's history had enough not-exact-set-match cards to make it
    visible - a 450-card singleton cube spanning many more distinct real
    sets than a typical ~100-card Commander deck was the first real case to
    actually hit it hard. Fixed with a functional index
    (`ix_scryfall_cards_name_lower` on `func.lower(name)`,
    `app/models/scryfall.py`) plus changing the query to `func.lower(name)
    == name.lower()` - verified live via `EXPLAIN ANALYZE`: ~865ms
    sequential scan down to ~0.9ms index scan, same worst-case (no-match)
    query. Note for future declarative-model functional indexes: `Index(...,
    func.lower(col))` inside `__table_args__` needs `col` to already exist
    as a class attribute, so `__table_args__` has to come *after* the
    column definitions in the class body, not before (unlike a plain
    string-column-name `Index(...)`, which resolves lazily and can go
    either place).
31. **A `job_timeout` sized off per-request pacing constants x page count
    (`POPULAR_DECKS_PAGES_PER_SORT` etc.) was not actually enough once
    those pool sizes were bumped a third time** (found live re-verifying
    the bracket filter, post-Phase-7) — the discovery sync's `job_timeout`
    stayed at 900s through two earlier pool-size increases without issue,
    but the third bump (Moxfield 5→50 pages/sort, Archidekt 5→200 pages)
    made a real sync attempt get killed by RQ's `JobTimeoutException` with
    *nothing* committed (the delete-then-reinsert per source only commits
    once that source's whole fetch completes), even though isolated
    per-request timing samples of both APIs taken during the same
    investigation showed nowhere near 900s of real work. Root cause wasn't
    conclusively pinned down — a retry immediately after doubling the
    timeout to 1800s completed in ~6.3 minutes, comfortably inside the
    *original* 900s window, suggesting the first attempt hit a one-off
    slowdown rather than a systematic problem — but the timeout was still
    doubled rather than left at a value already shown live to be
    insufficient once. Treat "this constant was fine at a smaller scale" as
    something to re-verify live after any further scale-up, not something
    that just linearly holds — a sync that used to comfortably fit its
    timeout can stop fitting after a pool-size change even if the naive
    per-request-time-times-request-count math still says it should.
32. **`app.comparison.leverage.compute_leverage`'s O(candidates x lists)
    shape, and `compare()`'s per-call owned-pool rebuild, were both fine at
    "dozens of decks/cubes" but became a real, live, site-wide outage once
    a real bulk import pushed the collection to 590+ lists** (found live:
    a user-triggered "select all" bulk import of the CubeCobra discovery
    cache). Symptom was `GET /api/dashboard` hanging past nginx's timeout
    (`HTTP 504`), which cascaded into blocking *unrelated* endpoints too
    (`GET /api/discover/decks` also appeared to hang) because this
    project's single uvicorn process has no worker pool - one request
    doing minutes of synchronous CPU-bound Python blocks every other
    concurrent request. Root cause, once profiled rather than guessed:
    `compare()` rebuilds its owned-card pool from scratch on every call
    (fine for one-off comparisons, ruinous when leverage calls it per
    candidate-times-list pair - confirmed 25,605 real distinct missing
    candidates across 590 real lists), *and* the leverage loop re-ran a
    full `compare()` against *every* list for *every* candidate even
    though only lists that actually require that candidate can possibly be
    affected. Fixed in three layers, each verified live against the real
    dataset before moving to the next: (1) split `compare()` into
    `build_owned_pool` (called once) + `compare_pool` (reads a pool,
    tracks per-call duplicate-line consumption in a small local dict
    instead of mutating/copying the shared pool - `app/comparison/
    engine.py`); (2) `compute_leverage` replaced the "re-run compare() per
    (candidate, list) pair" loop with pure dict lookups against each
    list's own precomputed baseline, since adding a candidate's full
    aggregate shortfall back to the pool always exactly satisfies every
    list that needs it (`app/comparison/leverage.py`); (3) `app.metrics.
    dashboard_service.compute_list_buildability` batched what was an
    N-queries-one-per-list DB fetch into one (`app.services.
    comparison_service.required_cards_by_list`), and that query itself was
    switched from full ORM-entity hydration to plain-column selects (260k+
    rows of `CardListItem` object instantiation was the dominant cost even
    after the N+1 fix). Net result on the real 590-list, 260,734-row
    dataset: `compute_leverage` went from "didn't finish in over two
    minutes, had to be killed" to ~4s; the full `/api/dashboard` response
    from an unbounded hang to ~6-7s. Not "infinitely fast" - a genuinely
    large real collection is still real work - but it completes promptly
    instead of pegging the process and taking the rest of the app down
    with it.
33. **`app.metrics.dashboard_service.compute_list_missing_cost`'s `IN
    (...)` clauses could exceed Postgres's real 65535-bound-parameter
    limit and hard-crash `/metrics` outright, not just run slowly** (found
    live investigating gotcha #32's incident: 23,829 distinct missing
    oracle_ids at the 590-list scale, fanning out to 433,497 individual
    printings before this was fixed). Fixed two ways: (1) any `IN` clause
    built from a real, potentially-large id set is now chunked into
    batches of 5,000 (`_chunked` helper) so no single query can ever hit
    the parameter ceiling regardless of how large the real set grows; (2)
    the printings-by-oracle lookup was rewritten from "fetch every
    printing of every candidate oracle_id, then separately fetch prices
    for all of them" into one JOINed query per chunk that only returns
    printings that actually *have* a price in the profile's currency/foil
    - real decks/cubes only have prices for a fraction of all printings,
    so this touches far fewer rows than fetching the full printing set
    first. A third, separate fix in the same investigation: the per-
    candidate cheapest-price lookup was being recomputed from scratch for
    every *missing line* (255k+ across all lists) instead of once per
    *distinct* oracle_id (~24k) - caching it cut a redundant ~10x factor.
    Combined, `/metrics` went from a hard crash to ~5.6s on the real
    dataset - see gotcha #27 for the original batching this built on top
    of, which turned out insufficient once real list counts grew this far
    past "a household's dozen or so decks."
34. **A real CubeCobra CSV export can have a malformed row that silently
    breaks column alignment for everything after it, in two different
    ways this project hit live** - both traced to a free-text cell (a
    card's own "Notes" field) containing an unescaped quote character,
    which shifts every later column on that one row. (a) `csv.DictReader`
    stashes the resulting overflow under a `None` key, and `csv.
    DictWriter`'s default `extrasaction="raise"` aborted the *entire*
    cube's import over that one row (`app/source_adapters/cubecobra.py`
    `_inject_quantity_column`, fixed with `extrasaction="ignore"` - safe
    here specifically because every field this adapter actually maps sits
    earlier in the row than where real CubeCobra exports break). (b) A
    worse case of the same shift landed an unrelated 17-character artist
    name in the 16-character `set_code` column, which `_inject_quantity_
    column`'s fix doesn't touch (the value fit into a *real* column, it
    was just too long for it) - this raised a raw `psycopg.errors.
    StringDataRightTruncation` from `confirm_import`'s bulk insert and
    aborted that entire list's confirm. Fixed generally, not CubeCobra-
    specifically, since any source's data could in principle be too long
    for its column: `app.services.list_import_service.confirm_import` now
    truncates every string field to its own `CardListItem` column width
    before insert (`_truncate` helper) - "one malformed row" now degrades
    to "one row with wrong/truncated data" instead of sinking the other
    ~250 good rows in the same import. Both found live via a real 808-cube
    bulk-import load test (see below), not synthetic testing.
35. **A same-named list is not proof it's the same cube** - two distinct
    real CubeCobra cubes can share an identical display name (confirmed
    live against real data: 26 different names, one - "Commander Cube" -
    shared by 5 different owners' real, different cubes). The first
    version of `import_popular_cube`'s "adopt an existing same-named list
    instead of crashing on the `(user_id, name)` uniqueness constraint"
    logic (see the "Discover Cubes" feature paragraph below) didn't check
    for this, and live data confirmed it went wrong twice for real: one
    list ended up referenced by two different `PopularCube` rows at once,
    and in one case a 540-card cube got silently marked "imported" against
    a *different* cube's real 548-card list. Fixed by checking, before
    ever adopting or reusing a same-named list, whether that name is
    ambiguous (more than one distinct `external_id` currently shares it) -
    an ambiguous cube always gets its own disambiguated list name
    (`f"{name} ({short_id})"`) instead of ever touching a list that might
    belong to a different real cube. The two already-corrupted rows found
    live were corrected by hand (one had a real matching item count and
    was left linked; the other two were genuinely indistinguishable by
    count alone and were reset to unlinked, re-importable state) - see
    ARCHITECTURE.md for why "keep the real card lists, just fix the
    linking" was the right call rather than deleting anything.
36. **Growth from a real user-triggered load test (gotcha #32's incident,
    and the follow-up 808/703-cube import runs) pushed `/metrics` past
    Prometheus's own bare 10s `scrape_timeout` default, silently breaking
    every Grafana panel fed by it** - Grafana showed "No data", not an
    error, since Prometheus was discarding every scrape as a timeout
    rather than reporting a query failure. Confirmed live via Prometheus's
    own `/api/v1/targets` (`"health":"down"`, `"lastError":"...context
    deadline exceeded"`) - `/metrics` itself was healthy and returning
    correct data (~13s at 1,446 real lists), just too slow for the
    *default* timeout neither `prometheus.yml` nor gotcha #33's fix had
    made explicit. Fixed by setting `scrape_interval`/`scrape_timeout`
    explicitly and generously (60s / 45s, this data doesn't need sub-
    minute freshness) rather than chasing the exporter's compute time down
    further - `compute_list_buildability`'s remaining cost at this scale
    is genuine per-list comparison work, not redundant computation like
    gotchas #32/#33 found, so there's no more "free" algorithmic win left
    without a materially bigger change (e.g. pushing comparison into SQL,
    or caching the exporter's own output). Treat "does this background
    job/scrape still fit its timeout" as something to re-check after any
    further real data growth, the same lesson as gotcha #31.
37. **User-requested: basic lands (Plains/Island/Swamp/Mountain/Forest/
    Wastes, snow-covered variants included) are excluded from the
    Dashboard's "what to buy next" leverage ranking** - confirmed via real
    data that they dominated it purely because real decks/cubes want them
    in bulk (thousands of copies summed across hundreds of lists inflates
    `total_coverage_gain` far past any single-copy candidate), not because
    buying them is a real decision anyone needs ranked advice on (unlike
    every other card here, basic lands are never actually scarce).
    Filtered by exact case-insensitive name in `app.metrics.
    dashboard_service.get_dashboard_summary`, applied to the *full*
    candidate list before truncating to `TOP_LEVERAGE_COUNT` - filtering
    after truncation would silently return fewer than 10 real
    recommendations whenever a basic land would otherwise have placed.

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
