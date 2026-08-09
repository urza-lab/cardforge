# SOURCE_ADAPTERS

CardForge's source-adapter system is designed so every external source is
optional and swappable, and manual import always works as a fallback.
**Status: interface defined in Phase 1; adapters land in Phases 3/5/6.**

**Scryfall (Phase 3, done):** implemented as `app/source_adapters/scryfall.py`
— bulk-data download/parse/mirror into `scryfall_cards`, triggered
automatically on first start (or manually from the System Status page) and
run as an RQ job. It's a one-file bulk sync, not shaped like the generic
`SourceAdapter` protocol below (no `validate_url`/`fetch_by_url` — there's no
per-list URL to fetch), so it doesn't implement that protocol; the REST
single-card fallback mentioned in the table below is not yet built (deferred
until a feature needs a single-card lookup, e.g. a Phase 4 card detail
page).

## Adapter interface

Every adapter (`backend/app/source_adapters/`) implements the same shape:

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
| MTGJSON | api | 6 | Pricing data, where suitable data is available |
| Moxfield public URL | public_url | 5 | Deck + collection URLs, no login |
| Archidekt public URL | public_url | 5 | Deck URLs; collection URLs experimental |
| Cardmarket | api | 6 | Optional, off by default |
| Generic configurable source | api/public_url | 5 | User-defined endpoint template |

## Status values

Every source and every refresh attempt reports one of:

`CURRENT`, `STALE`, `FETCHING`, `FAILED`, `AUTH_REQUIRED`, `NOT_FOUND`,
`RATE_LIMITED`, `SOURCE_CHANGED`, `PARSE_ERROR`, `DISABLED`.

A failed refresh never deletes or blanks out the last successful data — see
`SECURITY.md` and the refresh system design in `ARCHITECTURE.md`.

## Rules all adapters follow

- Never store third-party login credentials.
- Never automate a login form.
- Never bypass a CAPTCHA or other access control.
- Never fetch a private/authenticated URL — if a page requires login,
  return `AUTH_REQUIRED` and point the user at manual import instead.
- Public URL adapters run every request through the SSRF guard described in
  `SECURITY.md` (blocks private IP ranges, localhost, non-http(s) schemes).
- Rate limits and timeouts are configured per source (see **Sources** in the
  UI) and enforced centrally, not just "best effort" inside each adapter.

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

Implement the `SourceAdapter` protocol, register it in
`app/source_adapters/__init__.py`, and add a row to `source_configs` via a
migration. No changes to the comparison engine or UI navigation are needed —
both are adapter-agnostic.
