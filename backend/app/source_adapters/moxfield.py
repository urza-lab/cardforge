"""Moxfield public deck import — see SOURCE_ADAPTERS.md. Fetches the same
public JSON API moxfield.com's own frontend uses (no API key, no login
needed for public decks) — confirmed against a real public deck during
Phase 5 development.

Produces the same `ParseResult`/`ParsedRow` shape as the manual list parsers
(app/parsers/list_text.py, app/parsers/json_list.py) rather than a separate
"ParsedList" type from SOURCE_ADAPTERS.md's illustrative Protocol sketch —
see ARCHITECTURE.md "Documented default decisions" for why: the actual
pipeline (app/services/list_import_service.py) only ever needs one row
shape to build CardListItem rows from, whichever adapter produced it.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.parsers.common import ParsedRow, ParseResult
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult, PopularDeckEntry
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

SOURCE_NAME = "moxfield"
API_BASE = "https://api.moxfield.com/v2/decks/all"

# Real public search API moxfield.com's own "browse decks" page uses -
# confirmed live during development (sortType accepts "views"/"likes"/
# "created"/"updated"/"name", not "trending"/"popularity"/"hot"; no "cube"
# fmt value exists here, so this only ever discovers decks, never cubes -
# see SOURCE_ADAPTERS.md "Documented default decisions").
SEARCH_API = "https://api.moxfield.com/v2/decks/search"
POPULAR_DECKS_PAGE_SIZE = 100
# 50 pages x 100/page = 5,000 raw rows per sort - bumped again after a
# second user request for a much bigger pool. Moxfield's search API hard-
# caps at 10,000 results (100 pages) per sort regardless (confirmed live -
# page 100/100 still real data, page 101 empty); 50 stays well short of
# that ceiling while keeping sync time reasonable (100 requests total
# across both sorts x 1.5s pacing ~= 150s).
POPULAR_DECKS_PAGES_PER_SORT = 50
POPULAR_DECKS_SORTS = ("views", "likes")
# A real 429 was hit during development after firing off many unique-query
# requests back-to-back with no pacing at all - a small delay between each
# of this sync's few requests keeps it respectful of Moxfield's servers.
POPULAR_DECKS_REQUEST_DELAY_SECONDS = 1.5

# Real, working per-ID card lookup (confirmed live: "E5bmd" ->
# "Winota, Joiner of Forces") - the only way to get a real commander name at
# all, since Moxfield's search API has no working commander-name filter of
# its own (confirmed live: guessed query param names were silently ignored,
# proven via a nonsense-value control request returning identical results).
# No bulk/batch variant was found, so this is paced the same as everything
# else here - see resolve_commander_names.
COMMANDER_LOOKUP_API = "https://api.moxfield.com/v1/cards"

# Moxfield's own top-level board buckets map directly to our section enum
# (app.models.lists.ListItemSection) except "commanders"/"companions" -
# plural bucket *names* holding what's still logically one card each.
_SECTION_BUCKETS = {
    "mainboard": "mainboard",
    "sideboard": "sideboard",
    "maybeboard": "maybeboard",
    "commanders": "commander",
    "companions": "companion",
}


def validate_url(url: str) -> bool:
    try:
        extract_deck_id(url)
    except InvalidUrlError:
        return False
    return True


def extract_deck_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"moxfield.com", "www.moxfield.com"}:
        raise InvalidUrlError(f"'{url}' is not a moxfield.com URL")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "decks":
        raise InvalidUrlError(f"'{url}' doesn't look like a Moxfield deck URL (expected /decks/<id>)")
    return parts[1]


def fetch_and_parse(url: str, user_agent: str) -> DeckFetchResult:
    deck_id = extract_deck_id(url)
    resp = guarded_get(f"{API_BASE}/{deck_id}", headers={"User-Agent": user_agent, "Accept": "application/json"})

    if resp.status_code in (401, 403):
        raise AuthRequiredError(f"Moxfield deck '{deck_id}' requires login (private or restricted)")
    if resp.status_code == 404:
        raise SourceFetchError(f"Moxfield deck '{deck_id}' not found")
    if resp.status_code != 200:
        raise SourceFetchError(f"Moxfield returned HTTP {resp.status_code} for deck '{deck_id}'")

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(f"Moxfield returned non-JSON response for deck '{deck_id}'") from exc

    result = ParseResult(detected_columns={"format": "moxfield", "deck_id": deck_id})
    row_number = 0
    for bucket_name, section in _SECTION_BUCKETS.items():
        bucket = data.get(bucket_name)
        if not isinstance(bucket, dict):
            continue
        for card_name, entry in bucket.items():
            row_number += 1
            result.rows.append(_map_entry(row_number, card_name, entry, section))
    return DeckFetchResult(deck_name=data.get("name"), parse_result=result)


def _map_entry(row_number: int, fallback_name: str, entry: dict[str, Any], section: str) -> ParsedRow:
    card = entry.get("card") or {}
    raw = {"name": fallback_name, "section": section, **entry}

    name = card.get("name") or fallback_name
    quantity = entry.get("quantity")
    if not isinstance(quantity, int) or quantity <= 0:
        return ParsedRow(row_number=row_number, raw=raw, error=f"quantity '{quantity}' is not a positive integer")

    set_code = card.get("set")
    mapped = {
        "name": name,
        "set_code": set_code.upper() if set_code else None,
        "set_name": card.get("set_name"),
        "collector_number": card.get("cn"),
        "quantity": quantity,
        "foil": bool(entry.get("isFoil", False)),
        # Moxfield's card object already pins the exact printing via
        # scryfall_id; no separate language field to read.
        "language": None,
        "scryfall_id": card.get("scryfall_id"),
        "section": section,
        "category": None,
        "tags": None,
    }
    return ParsedRow(row_number=row_number, raw=raw, mapped=mapped)


def attribution(deck_url: str) -> str:
    return f"Imported from Moxfield: {deck_url}"


def fetch_popular_decks(user_agent: str, *, fmt: str = "commander") -> list[PopularDeckEntry]:
    """Real public data, not a curated/hardcoded list - queries Moxfield's
    own search API sorted by view count and by like count (two real
    popularity signals), merges and dedupes by publicId. Deliberately not
    called on every browse request (see app/models/discover.py) - this is
    the sync job's job, run on demand via POST /api/discover/decks/sync.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    by_id: dict[str, PopularDeckEntry] = {}

    first_request = True
    for sort_type in POPULAR_DECKS_SORTS:
        for page in range(1, POPULAR_DECKS_PAGES_PER_SORT + 1):
            if not first_request:
                time.sleep(POPULAR_DECKS_REQUEST_DELAY_SECONDS)
            first_request = False

            resp = httpx.get(
                SEARCH_API,
                params={"pageNumber": page, "pageSize": POPULAR_DECKS_PAGE_SIZE, "sortType": sort_type, "fmt": fmt},
                headers=headers,
                timeout=30,
            )
            if resp.status_code != 200:
                raise SourceFetchError(
                    f"Moxfield popular-decks search returned HTTP {resp.status_code} "
                    f"(sortType={sort_type}, page={page})"
                )
            for entry in resp.json().get("data", []):
                public_id = entry.get("publicId")
                if not public_id:
                    continue
                by_id[public_id] = PopularDeckEntry(
                    external_id=public_id,
                    name=entry.get("name") or "(untitled)",
                    author=(entry.get("createdByUser") or {}).get("displayName"),
                    source_url=entry.get("publicUrl") or f"https://moxfield.com/decks/{public_id}",
                    format=entry.get("format") or fmt,
                    view_count=entry.get("viewCount") or 0,
                    like_count=entry.get("likeCount") or 0,
                    color_identity=entry.get("colorIdentity"),
                    has_primer=bool(entry.get("hasPrimer", False)),
                    deck_size=entry.get("mainboardCount"),
                    comment_count=entry.get("commentCount") or 0,
                    bookmark_count=entry.get("bookmarkCount") or 0,
                    deck_updated_at=_parse_moxfield_timestamp(entry.get("lastUpdatedAtUtc")),
                    tags=entry.get("hubNames") or None,
                    main_card_id=entry.get("mainCardId"),
                )

    return list(by_id.values())


def _parse_moxfield_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def iter_resolved_commander_names(
    main_card_ids: set[str], user_agent: str, *, known: dict[str, str] | None = None
) -> Iterator[tuple[str, str]]:
    """Resolves each Moxfield-internal `mainCardId` to its real card name via
    `GET /v1/cards/{id}` - for a Commander-format deck, the "main card" is
    the commander itself (the same assumption `fetch_popular_decks` already
    stores as `main_card_id`). One request per ID, paced the same as the
    rest of this module - no bulk lookup endpoint was found live.

    A *generator*, not a function returning a full dict, so a caller
    (discover_service) can persist each resolution to
    app.models.discover.MoxfieldCommanderCache as it arrives instead of only
    at the very end - real cost here is large (~1.7h for a first full
    resolution across this project's real ~6,300-deck Moxfield cache,
    confirmed live via sampling) and a mid-run crash/worker-restart (see
    CLAUDE.md gotcha #29 - not hypothetical, worker restarts happen
    routinely during dev) shouldn't discard everything already resolved.

    `known` lets a caller skip IDs already resolved by a previous run - a
    card's name never changes, so a resync only ever pays for genuinely new
    commanders, not the full set every time. A 404 (a mainCardId pointing
    at a removed/invalid card) or any other non-200 response is skipped
    rather than raised - one bad ID shouldn't abort the whole sync over a
    single unresolved commander name.
    """
    known = known or {}
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    to_fetch = [mid for mid in main_card_ids if mid and mid not in known]

    first = True
    for main_card_id in to_fetch:
        if not first:
            time.sleep(POPULAR_DECKS_REQUEST_DELAY_SECONDS)
        first = False

        resp = httpx.get(f"{COMMANDER_LOOKUP_API}/{main_card_id}", headers=headers, timeout=15)
        if resp.status_code != 200:
            continue
        try:
            name = (resp.json().get("card") or {}).get("name")
        except ValueError:
            continue
        if name:
            yield main_card_id, name
