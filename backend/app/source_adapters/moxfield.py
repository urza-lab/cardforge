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

from typing import Any
from urllib.parse import urlparse

from app.parsers.common import ParsedRow, ParseResult
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

SOURCE_NAME = "moxfield"
API_BASE = "https://api.moxfield.com/v2/decks/all"

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
