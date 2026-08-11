# SOURCE_ADAPTERS

CardForge's source-adapter system is designed so every external source is
optional and swappable, and manual import always works as a fallback.
**Status: interface defined in Phase 1; Scryfall (Phase 3); Moxfield and
Archidekt (Phase 5); MTGJSON (Phase 6) are all done. No direct Cardmarket
API adapter — see below.**

**Scryfall (Phase 3, done):** implemented as `app/source_adapters/scryfall.py`
— bulk-data download/parse/mirror into `scryfall_cards`, triggered
automatically on first start (or manually from the System Status page) and
run as an RQ job. It's a one-file bulk sync, not shaped like the generic
`SourceAdapter` protocol below (no `validate_url`/`fetch_by_url` — there's no
per-list URL to fetch), so it doesn't implement that protocol; the REST
single-card fallback mentioned in the table below is not yet built (deferred
until a feature needs a single-card lookup).

**Moxfield / Archidekt (Phase 5, done):** implemented as
`app/source_adapters/moxfield.py` / `archidekt.py` — real JSON API fetchers
(`api.moxfield.com/v2/decks/all/{id}`, `archidekt.com/api/decks/{id}`),
verified against live public decks during development. **Deck URLs only —
collection URLs are not implemented** (the table below's original "collection
URLs experimental" note never landed; scope stayed to decks/cubes, matching
the rest of the app). Neither implements the generic `SourceAdapter`
protocol below: their output maps directly onto the same `ParseResult`/
`ParsedRow` shape the text/JSON/CSV list parsers already produce
(`app/source_adapters/common.py`'s `DeckFetchResult`), so
`app/services/list_import_service.py` and `list_refresh_service.py` handle
URL-sourced and file-sourced imports through one pipeline instead of a
separate `fetch_by_url`/`normalize` path — see ARCHITECTURE.md "Documented
default decisions". A `CardList` imported from a URL can be refreshed
(`POST /api/lists/{id}/refresh`, or automatically by a periodic staleness
sweep — see `app/services/list_refresh_service.py` and
`app/workers/run_worker.py`); a refresh replaces the list's items wholesale
rather than diffing, and never touches the list if nothing changed.

**Deck discovery — Moxfield + Archidekt (post-Phase-7, done, user-requested):**
`app/services/discover_service.py`'s `run_discovery_sync` — a real
popularity-ranked deck browser ("what's worth importing"), not a
curated/hardcoded list, now backed by two independent real sources rather
than one:

- **Moxfield**: `app/source_adapters/moxfield.py`'s `fetch_popular_decks`
  queries the public `/v2/decks/search` endpoint (`sortType=views` and
  `sortType=likes`, `fmt=commander`, `POPULAR_DECKS_PAGES_PER_SORT = 5`
  pages of 100/page per sort), merging/deduping both sorts by `publicId`.
- **Archidekt**: an initial check during the original discovery work
  concluded Archidekt's search needed authentication - that was wrong, just
  an incomplete check (the real search API lives at a different, undocumented
  path). `app/source_adapters/archidekt.py`'s `fetch_popular_decks` was
  added later, found by scraping archidekt.com/search/decks's own HTML for
  embedded API paths: the real public endpoint is `/api/decks/v3/`
  (`formats=3` = Commander/EDH, `orderBy=-viewCount`). Confirmed live only
  `-viewCount` is trustworthy — `-points`/`-favorites`/`-likes` returned
  suspiciously tiny 5-14 card decks, suggesting a silent fallback rather
  than an honored sort, so Archidekt decks are only ever ranked by views
  (`like_count` is always 0 for this source, not fabricated). The API
  ignores `pageSize`/`size`/`limit` entirely and always returns a fixed 60
  results/page (confirmed live, undocumented) - `POPULAR_DECKS_PAGES = 5`
  (~300 decks). No `colorIdentity` field exists; `colors` (a per-WUBRG
  percentage-of-cards breakdown) is used as an approximation instead - keys
  with a nonzero value become the deck's `color_identity` for filtering.

Both sources share one `PopularDeckEntry` shape
(`app/source_adapters/common.py`) and sync into the same local
`popular_decks` cache (`POST /api/discover/decks/sync`,
`GET /api/discover/decks/status`,
`GET /api/discover/decks?sort=...&color_identity=...&source=...`) — never
queried live per browse request (see ARCHITECTURE.md for why). A single
source failing (e.g. a real Moxfield 429) doesn't lose the other source's
already-cached decks or block its own resync - see
`discover_service.run_discovery_sync`'s docstring; the sync only ends
FAILED if every source failed. **Deck URLs only, same as the URL-import
adapters above** — Moxfield's search endpoint has no `cube` format value
and Archidekt's has no cube-equivalent format id either, so Commander decks
only remains a deliberate scope decision (user asked, evaluated the
options, chose "decks now, skip cubes rather than ship something
half-working"), not an oversight.

A real sync (2026-08-10) cached 693 real Moxfield decks + 300 real
Archidekt decks = 993 total, including a real 402k-view Archidekt deck; a
real one-click import of an Archidekt-discovered deck through the existing
URL-import pipeline succeeded (81/81 rows, 0 errors) with no adapter
changes needed beyond the discovery sync itself, confirming
`app/source_adapters/archidekt.py`'s existing `fetch_and_parse`/deck-URL
shape (Phase 5) already lined up with the discovery API's deck IDs.

**EDHREC synthesized decks (post-Phase-7, done, user-requested):**
`app/source_adapters/edhrec.py` — fundamentally different from the other
adapters above: EDHREC has no hosted decklists and no public API at all. It
is a Next.js SSG site that embeds real per-page data in a `__NEXT_DATA__`
`<script>` tag (found the same way Archidekt's real search API was found -
inspecting a page's own client-side data rather than guessing endpoint
paths). Two real EDHREC data shapes are used:

- `/commanders`'s own "Past 2 Years" cardlist — a real, ranked top-100
  popularity list of commanders (`fetch_popular_commanders`).
- Each commander's own page (`/commanders/{slug}`) exposes both its real
  *average deck composition* (`creature`/`instant`/.../`land` counts - e.g.
  Atraxa: 24 creatures, 10 instants, ..., 35 lands, summing to exactly 99)
  and ranked, most-played-first card pools per category (`cardlists`).
  `fetch_and_synthesize` combines the two: pick the top N cards per
  category up to that commander's own real average count, synthesize
  basic-land copies from its color identity (EDHREC's land pool isn't
  quantity-aware — a basic land appears once in the ranking regardless of
  how many copies real decks run), and build a plain decklist text
  (`app/parsers/list_text.py`'s "Commander: X" + one name per line format).

This is a genuinely different feature from Moxfield/Archidekt discovery,
not just a third source in the same list — the result is a *computed*
deck, not one a real person built, so it's kept in its own model
(`app/models/edhrec.py` `SynthesizedDeck`, its own sync state, its own
`GET /api/edhrec/decks` / `.../status` / `POST .../sync` endpoints) and its
own frontend tab (`frontend/src/pages/EdhrecDecks.tsx`), not merged into
`PopularDeck`/Discover — a deliberate choice (user asked, given the "real
findings vs a materially different shape" tradeoff, chose a separate tab
over mixing sources with different meanings into one badge-qualified list).
Import still reuses the existing pipeline with zero new import logic, just
a different existing entry point than the URL adapters: since there's no
URL to fetch at import time (the decklist was already synthesized and
stored at sync time), importing a cached `SynthesizedDeck` goes through the
existing upload-based `POST /api/list-imports/preview` (source_type=`text`,
the stored `deck_text` sent as a file) rather than `preview-url` -
create-list → preview (as a file) → confirm, the same three calls
"Import Lists → File/paste" already makes for a manually pasted text list.

A real sync (2026-08-10) synthesized all 100 real top commanders (~600-700KB
HTML per page, ~88 seconds total, one real 429-free run) with zero
per-commander failures; a real import of the top-ranked synthesized deck
("The Ur-Dragon", 49,562 real EDHREC decks) landed 100/100 rows with 0
parse errors (99 cards + commander) through the unmodified text-import
pipeline.

**MTGJSON (Phase 6, done):** implemented as `app/source_adapters/mtgjson.py`
— a real price-data sync (`AllIdentifiers.json.xz` + `AllPricesToday.json`,
see PRICING.md for the full join logic), its own `PriceSyncState`
FETCHING/CURRENT/FAILED row (`POST /api/mtgjson/sync`,
`GET /api/mtgjson/status`), run as its own RQ job on the same `pricing`
queue Phase 6 reserved in `app/workers/run_worker.py`. Also doesn't
implement the generic `SourceAdapter` protocol below — same reasoning as
Scryfall's own sync (a bulk data-mirror sync doesn't need
`validate_url`/`fetch_by_url`/`search`). **No direct Cardmarket API
adapter was built**: Cardmarket's own API needs OAuth app
registration/approval, real friction for a self-hosted hobby tool, and
MTGJSON's `AllPricesToday.json` already relays real Cardmarket retail
prices (EUR) without that — see PRICING.md and ARCHITECTURE.md "Documented
default decisions". A direct adapter remains a real possible future
addition if MTGJSON's relay ever proves insufficient.

## Adapter interface

This was the original Phase 1 design for a shape every adapter would
implement. In practice, none of the four adapters actually built so far
(Scryfall, Moxfield, Archidekt, MTGJSON) implement it as a literal
`Protocol` — each's real shape turned out simpler than this aspirational
one once there was a concrete adapter to build against (see each adapter's
own note above). Kept here as the reference design in case a future
adapter (a direct Cardmarket API, say) actually needs the fuller shape
(`search`, `rate_limit`, `health_check`) none of the four built so far
did:

```python
class SourceAdapter(Protocol):
    source_name: str
    source_type: str  # "manual" | "file" | "api" | "public_url"

    def validate_url(self, url: str) -> bool: ...
    def fetch_by_url(self, url: str) -> FetchResult: ...
    def search(self, query: str) -> list[SearchResult]: ...
    def parse(self, raw: bytes | str) -> ParsedList: ...
    def normalize(self, parsed: ParsedList) -> NormalizedList: ...
    def attribution(self) -> str: ...
    def rate_limit(self) -> RateLimit: ...
    def health_check(self) -> HealthStatus: ...
```

## Planned adapters

| Adapter | Type | Phase | Notes |
|---|---|---|---|
| Manual text import | manual | 2 | Always available, no network |
| CSV upload | file | 2 | Generic + ManaBox column detection |
| JSON upload | file | 2 | |
| Scryfall | api | 3 | Bulk data + REST fallback for single-card lookups |
| Moxfield public URL | public_url | 5, done | Deck URLs only, no login |
| Archidekt public URL | public_url | 5, done | Deck URLs only, no login |
| Deck/cube CSV upload | file | 5, done | See IMPORT_FORMATS.md "Deck/cube CSV" |
| MTGJSON | api | 6, done | Price data — see PRICING.md |
| Moxfield + Archidekt deck discovery | api | post-7, done | Popular Commander decks only, no cubes, two sources merged — see above |
| EDHREC synthesized decks | scrape (`__NEXT_DATA__`) | post-7, done | Computed "average deck" per top-100 commander, not a real decklist — see above |
| Cardmarket (direct API) | api | not planned | MTGJSON already relays real Cardmarket EUR retail data — see PRICING.md |
| Generic configurable source | api/public_url | not planned | No concrete need yet — not scheduled |
| Moxfield/CubeCobra cube discovery | api | not planned | No public Moxfield cube-search API found; a CubeCobra adapter would be new, unverified work |

## Status values

The full set below is this doc's original aspirational design for a generic
multi-provider status system. What's actually implemented (Phase 5,
`app/models/lists.py` `ListRefreshStatus`, scoped to per-`CardList` URL
refresh, not a generic per-source registry) is a subset:
`FETCHING`, `CURRENT`, `FAILED`, `AUTH_REQUIRED`. `STALE` is computed on
read from `last_refreshed_at`, not a stored/reported status (see
ARCHITECTURE.md). `NOT_FOUND`, `RATE_LIMITED`, `SOURCE_CHANGED`,
`PARSE_ERROR`, and `DISABLED` are not distinguished yet — a 404 or a parse
failure both currently surface as `FAILED` with a detail message in
`refresh_error`; splitting them out is deferred until something needs to
react to them differently.

A failed refresh never deletes or blanks out the last successful data — a
refresh only replaces a list's items once the fetch and parse have both
already succeeded (see `app/services/list_refresh_service.py`).

## Rules all adapters follow

- Never store third-party login credentials.
- Never automate a login form.
- Never bypass a CAPTCHA or other access control.
- Never fetch a private/authenticated URL — if a page requires login,
  return `AUTH_REQUIRED` and point the user at manual import instead.
- Public URL adapters run every request through the SSRF guard described in
  `SECURITY.md` (blocks private IP ranges, localhost, non-http(s) schemes).
- Rate limits/timeouts are hardcoded per adapter (`httpx` call timeouts),
  not yet a per-source configurable setting in the UI — there is no
  **Sources** management UI for that; the Sources page (Phase 5) lists
  URL-sourced lists and their refresh status only.

## Attribution

- **Scryfall**: card data and images are provided by Scryfall
  (scryfall.com). CardForge is not endorsed or affiliated with Scryfall or
  Wizards of the Coast.
- **MTGJSON**: pricing/card data, where used, is provided by MTGJSON
  (mtgjson.com) under its terms.
- **Moxfield / Archidekt**: decklist data fetched via public URLs is
  attributed with a link back to the original list on every imported deck's
  detail page.

## Adding a new adapter

For a URL-based list adapter (the Moxfield/Archidekt shape): implement
`validate_url`/`fetch_and_parse`/`attribution` (see `moxfield.py` for the
minimal real shape — there's no `SourceAdapter` Protocol base class to
inherit from, just a matching function signature) and add it to
`URL_ADAPTERS` in `app/services/list_import_service.py`; also add its name
to `ListImportSourceType` (`app/models/lists.py`). No migration is needed
(there is no generic `source_configs` table — see "Status values" above for
why that part of this doc's original design didn't get built). No changes
to the comparison engine or UI navigation are needed — both are
adapter-agnostic.
