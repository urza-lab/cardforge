"""Archidekt public deck import — see SOURCE_ADAPTERS.md. Fetches the same
public JSON API archidekt.com's own frontend uses (no API key, no login
needed for public decks) — confirmed against a real public deck during
Phase 5 development. See app/source_adapters/moxfield.py's module docstring
for why this produces the shared `ParseResult` shape rather than a
standalone type.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.parsers.common import ParsedRow, ParseResult
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult, PopularDeckEntry
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

SOURCE_NAME = "archidekt"
API_BASE = "https://archidekt.com/api/decks"

# Real public search API archidekt.com/search/decks uses - found by scraping
# that page's own HTML for embedded API paths (not documented anywhere), then
# verified live: `orderBy=-viewCount` returns real, plausible-looking view
# counts (up to ~400k on the most-viewed deck seen during research);
# -points/-favorites/-likes all looked unreliable (returned tiny 5-14 card
# decks, suggesting a silent fallback to an unfiltered/default order rather
# than actually honoring the sort) so only -viewCount is used here. The API
# ignores pageSize/size/limit params entirely and always returns 60 results
# per page - confirmed live, not documented. `formats=3` is Commander/EDH -
# confirmed live by every result having `deckFormat: 3` and `size: 100`
# (99 + commander). No login/API key needed for this public search.
SEARCH_API = "https://archidekt.com/api/decks/v3/"
POPULAR_DECKS_PAGE_SIZE = 60  # fixed by the API - not configurable, see above
# 200 x 60 = up to 12,000 decks - bumped after a user request for a much
# bigger pool. No hard ceiling was found here (unlike Moxfield's real
# 10,000-per-sort cap) - live research paged as deep as 10,000 (600,000
# decks deep) and still got real, distinct decks back, but requests started
# timing out around page 50,000, so this stays comfortably shallow of that
# rather than chasing true exhaustiveness. Sync cost: 200 requests x 0.5s
# pacing ~= 100s.
POPULAR_DECKS_PAGES = 200
COMMANDER_FORMAT_ID = 3
# No 429 observed even firing 8 requests back-to-back during research, but a
# small delay keeps this respectful of Archidekt's servers the same way the
# Moxfield sync is (see app.source_adapters.moxfield's own delay constant).
POPULAR_DECKS_REQUEST_DELAY_SECONDS = 0.5

# Archidekt decks carry a free-form list of user-defined "categories" per
# card, not a fixed board enum - only a few names are Archidekt's own
# recognized special categories (mapped to our section enum below).
# Anything else becomes `category`/`tags` instead of a section.
_KNOWN_SECTION_CATEGORIES = {"commander": "commander", "sideboard": "sideboard", "maybeboard": "maybeboard"}


def validate_url(url: str) -> bool:
    try:
        extract_deck_id(url)
    except InvalidUrlError:
        return False
    return True


def extract_deck_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"archidekt.com", "www.archidekt.com"}:
        raise InvalidUrlError(f"'{url}' is not an archidekt.com URL")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "decks" or not parts[1].isdigit():
        raise InvalidUrlError(f"'{url}' doesn't look like an Archidekt deck URL (expected /decks/<id>)")
    return parts[1]


def fetch_and_parse(url: str, user_agent: str) -> DeckFetchResult:
    deck_id = extract_deck_id(url)
    resp = guarded_get(
        f"{API_BASE}/{deck_id}/", headers={"User-Agent": user_agent, "Accept": "application/json"}
    )

    if resp.status_code in (401, 403):
        raise AuthRequiredError(f"Archidekt deck '{deck_id}' requires login (private or restricted)")
    if resp.status_code == 404:
        raise SourceFetchError(f"Archidekt deck '{deck_id}' not found")
    if resp.status_code != 200:
        raise SourceFetchError(f"Archidekt returned HTTP {resp.status_code} for deck '{deck_id}'")

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(f"Archidekt returned non-JSON response for deck '{deck_id}'") from exc

    cards = data.get("cards")
    if not isinstance(cards, list):
        raise SourceFetchError(f"Archidekt deck '{deck_id}' response has no 'cards' list")

    result = ParseResult(detected_columns={"format": "archidekt", "deck_id": deck_id})
    for row_number, entry in enumerate(cards, start=1):
        result.rows.append(_map_entry(row_number, entry))
    return DeckFetchResult(deck_name=data.get("name"), parse_result=result)


def _map_entry(row_number: int, entry: dict[str, Any]) -> ParsedRow:
    card = entry.get("card") or {}
    oracle_card = card.get("oracleCard") or {}
    edition = card.get("edition") or {}
    raw = dict(entry)

    name = oracle_card.get("name")
    if not name:
        return ParsedRow(row_number=row_number, raw=raw, error="card entry has no name")

    quantity = entry.get("quantity")
    if not isinstance(quantity, int) or quantity <= 0:
        return ParsedRow(row_number=row_number, raw=raw, error=f"quantity '{quantity}' is not a positive integer")

    section = "mainboard"
    extra_categories: list[str] = []
    for category in entry.get("categories") or []:
        mapped_section = _KNOWN_SECTION_CATEGORIES.get(str(category).strip().lower())
        if mapped_section:
            section = mapped_section
        else:
            extra_categories.append(str(category))

    set_code = edition.get("editioncode")
    mapped = {
        "name": name,
        "set_code": set_code.upper() if set_code else None,
        "set_name": edition.get("editionname"),
        "collector_number": card.get("collectorNumber"),
        "quantity": quantity,
        "foil": str(entry.get("modifier", "")).lower() == "foil",
        "language": (oracle_card.get("lang") or "").upper() or None,
        "scryfall_id": card.get("uid"),
        "section": section,
        "category": extra_categories[0] if extra_categories else None,
        "tags": extra_categories or None,
    }
    return ParsedRow(row_number=row_number, raw=raw, mapped=mapped)


def attribution(deck_url: str) -> str:
    return f"Imported from Archidekt: {deck_url}"


def _extract_tag_names(raw_tags: Any) -> list[str] | None:
    """Real bug found live: Archidekt's search response `tags` field is a
    list of tag-assignment objects (`{"id": ..., "tag": <numeric id>,
    "name": "Sacrifice", "position": ...}`), not plain strings - storing
    these dicts directly crashed `GET /api/discover/decks` (see
    app/schemas/discover.py's PopularDeckRead validator, which normalizes
    already-stored rows the same way). The real tag name lives under
    `name`. Both shapes are handled defensively rather than assuming this
    is the only one Archidekt will ever return.
    """
    if not isinstance(raw_tags, list):
        return None
    names: list[str] = []
    for t in raw_tags:
        if isinstance(t, str):
            names.append(t)
        elif isinstance(t, dict) and isinstance(t.get("name"), str):
            names.append(t["name"])
    return names or None


def fetch_popular_decks(user_agent: str, *, fmt: int = COMMANDER_FORMAT_ID) -> list[PopularDeckEntry]:
    """Real public data from Archidekt's own search - see SEARCH_API above
    for what's actually confirmed to work. Unlike Moxfield, only one sort
    (view count) is trustworthy, so this doesn't merge multiple sorts - see
    app.source_adapters.moxfield.fetch_popular_decks for that pattern.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    by_id: dict[str, PopularDeckEntry] = {}

    for page in range(1, POPULAR_DECKS_PAGES + 1):
        if page > 1:
            time.sleep(POPULAR_DECKS_REQUEST_DELAY_SECONDS)

        resp = httpx.get(
            SEARCH_API,
            params={"formats": fmt, "orderBy": "-viewCount", "page": page},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            raise SourceFetchError(f"Archidekt popular-decks search returned HTTP {resp.status_code} (page={page})")

        results = resp.json().get("results", [])
        if not results:
            break

        for entry in results:
            deck_id = entry.get("id")
            if deck_id is None:
                continue
            external_id = str(deck_id)
            colors = entry.get("colors") or {}
            # Percentage-of-cards-per-color, not a true commander color
            # identity - the closest real signal this API exposes; used the
            # same way (subset-match filtering) as Moxfield's real
            # colorIdentity, see app.services.discover_service.
            color_identity = [c for c in ("W", "U", "B", "R", "G") if (colors.get(c) or 0) > 0]
            by_id[external_id] = PopularDeckEntry(
                external_id=external_id,
                name=entry.get("name") or "(untitled)",
                author=(entry.get("owner") or {}).get("username"),
                source_url=f"https://archidekt.com/decks/{deck_id}",
                format="commander",
                view_count=entry.get("viewCount") or 0,
                # No reliable likes/points signal was found on this API (see
                # SEARCH_API note above) - 0 rather than a fabricated number.
                like_count=0,
                color_identity=color_identity,
                bracket=entry.get("edhBracket"),
                has_primer=bool(entry.get("hasPrimer", False)),
                deck_size=entry.get("size"),
                theorycrafted=entry.get("theorycrafted"),
                comment_count=entry.get("comments") or 0,
                deck_updated_at=_parse_archidekt_timestamp(entry.get("updatedAt")),
                tags=_extract_tag_names(entry.get("tags")),
            )

    return list(by_id.values())


def _parse_archidekt_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def search_by_commander(commander_name: str, user_agent: str, *, fmt: int = COMMANDER_FORMAT_ID) -> set[str]:
    """Live, on-demand query against Archidekt's real `commanderName` search
    filter (confirmed live: unlike every other guessed param name here,
    this one genuinely changes the result set - a nonsense value returns
    zero results, real commander names return real matching decks). No
    stored metadata exists to search locally instead (Archidekt's search
    response never includes a commander field at all, confirmed by
    inspecting the full raw row shape), so this is only ever called on an
    explicit user action (submit/Enter, not on every keystroke - see
    app/api/discover.py), never as part of the regular cached sync.

    Returns the set of matching `external_id`s only, not full deck data -
    the caller (discover_service) intersects this against the already-
    cached Archidekt rows so color/bracket/price data stays sourced from
    the local cache, not this one-off live response.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    resp = httpx.get(
        SEARCH_API,
        params={"formats": fmt, "orderBy": "-viewCount", "commanderName": commander_name},
        headers=headers,
        timeout=10,
    )
    if resp.status_code != 200:
        raise SourceFetchError(f"Archidekt commander search returned HTTP {resp.status_code}")
    results = resp.json().get("results", [])
    return {str(entry["id"]) for entry in results if entry.get("id") is not None}
