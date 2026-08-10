"""Archidekt public deck import — see SOURCE_ADAPTERS.md. Fetches the same
public JSON API archidekt.com's own frontend uses (no API key, no login
needed for public decks) — confirmed against a real public deck during
Phase 5 development. See app/source_adapters/moxfield.py's module docstring
for why this produces the shared `ParseResult` shape rather than a
standalone type.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.parsers.common import ParsedRow, ParseResult
from app.security.ssrf_guard import AuthRequiredError, guarded_get
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.errors import InvalidUrlError, SourceFetchError

SOURCE_NAME = "archidekt"
API_BASE = "https://archidekt.com/api/decks"

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
