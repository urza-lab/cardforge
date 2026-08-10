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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.discover import (
    DISCOVERY_SYNC_STATE_ID,
    DeckDiscoverySyncState,
    DeckDiscoverySyncStatus,
    PopularDeck,
)
from app.parsers.common import ParsedRow, ParseResult
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult
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
POPULAR_DECKS_PAGES_PER_SORT = 2
POPULAR_DECKS_SORTS = ("views", "likes")
# A real 429 was hit during development after firing off many unique-query
# requests back-to-back with no pacing at all - a small delay between each
# of this sync's few requests keeps it respectful of Moxfield's servers.
POPULAR_DECKS_REQUEST_DELAY_SECONDS = 1.5


@dataclass(frozen=True)
class PopularDeckEntry:
    external_id: str
    name: str
    author: str | None
    source_url: str
    format: str
    view_count: int
    like_count: int
    color_identity: list[str] | None

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
                )

    return list(by_id.values())


def run_deck_discovery_sync(db: Session, settings: Settings | None = None) -> DeckDiscoverySyncState:
    """Refreshes the popular_decks cache from a real Moxfield search - same
    FETCHING/CURRENT/FAILED state machine and delete-then-reinsert-inside-
    one-transaction shape as app.source_adapters.scryfall.run_bulk_sync,
    scoped to source="moxfield" only (a future second discovery source
    would delete/reinsert its own source's rows the same way, leaving
    others untouched).
    """
    settings = settings or get_settings()
    state = db.get(DeckDiscoverySyncState, DISCOVERY_SYNC_STATE_ID)
    if state is None:
        raise SourceFetchError("deck_discovery_sync_state row is missing - has the migration been applied?")

    state.status = DeckDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        decks = fetch_popular_decks(settings.scryfall_user_agent)

        db.execute(delete(PopularDeck).where(PopularDeck.source == SOURCE_NAME))
        if decks:
            db.execute(
                insert(PopularDeck),
                [
                    {
                        "source": SOURCE_NAME,
                        "external_id": d.external_id,
                        "name": d.name,
                        "author": d.author,
                        "source_url": d.source_url,
                        "format": d.format,
                        "view_count": d.view_count,
                        "like_count": d.like_count,
                        "color_identity": d.color_identity,
                    }
                    for d in decks
                ],
            )

        state.status = DeckDiscoverySyncStatus.current.value
        state.deck_count = len(decks)
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = db.get(DeckDiscoverySyncState, DISCOVERY_SYNC_STATE_ID)
        assert state is not None
        state.status = DeckDiscoverySyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state
