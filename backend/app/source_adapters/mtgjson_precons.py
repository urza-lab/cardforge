"""Real official Commander preconstructed decks from MTGJSON's bulk deck
data — see app/models/mtgjson_precons.py for why this is a materially
different kind of "discover a deck" source from Moxfield/Archidekt/
CubeCobra/EDHREC. Two real MTGJSON endpoints, both already-trusted (the
same domain Phase 6's price sync pulls from):

- `GET /api/v5/DeckList.json` - a real manifest of every deck MTGJSON has
  data for (3,004 total live-checked, spanning Theme Decks, Secret Lair
  Drops, Jumpstart, etc.) - filtered here to `type == "Commander Deck"`
  (190 real official Commander precons, live-checked).
- `GET /api/v5/decks/{fileName}.json` - one real deck's full content per
  file. Each card carries `identifiers.scryfallOracleId` directly, so
  cards resolve to an oracle_id with zero name/set-code matching ambiguity
  - better resolution quality than any of the other deck-discovery sources,
  which all rely on some form of name or set+number matching.
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass

import httpx

from app.source_adapters.errors import SourceFetchError

DECK_LIST_URL = "https://mtgjson.com/api/v5/DeckList.json"
DECK_URL = "https://mtgjson.com/api/v5/decks/{file_name}.json"
COMMANDER_DECK_TYPE = "Commander Deck"
# No rate-limiting observed firing 5 rapid requests during research, but a
# small delay between the ~190 individual deck fetches a full sync makes
# keeps this respectful, same reasoning as every other adapter's own delay
# constant.
PRECON_REQUEST_DELAY_SECONDS = 0.3


@dataclass(frozen=True)
class PreconDeckEntry:
    file_name: str
    name: str
    commander_names: list[str]
    release_date: str | None
    source_url: str
    card_count: int
    cards: list[dict]
    deck_text: str


def _card_entry(card: dict) -> tuple[str, str | None, str | None, int]:
    identifiers = card.get("identifiers") or {}
    name = card.get("name") or ""
    oracle_id = identifiers.get("scryfallOracleId")
    scryfall_id = identifiers.get("scryfallId")
    count = card.get("count") or 1
    return name, oracle_id, scryfall_id, count


def _build_deck_text(commander_cards: list[dict], main_cards: list[dict]) -> tuple[str, list[dict], int]:
    """Builds a ready-to-import CSV (see app/parsers/list_csv.py's real
    header aliases - name/quantity/scryfall_id/section all match directly,
    no column_mapping override needed unlike CubeCobra's CSV) plus the
    plain {name, oracle_id, quantity} list used for live coverage
    computation (app.comparison.engine.compare).
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "quantity", "scryfall_id", "section"])

    cards: list[dict] = []
    total = 0
    for card, section in [(c, "commander") for c in commander_cards] + [(c, "mainboard") for c in main_cards]:
        name, oracle_id, scryfall_id, count = _card_entry(card)
        if not name:
            continue
        writer.writerow([name, count, scryfall_id or "", section])
        cards.append({"name": name, "oracle_id": oracle_id, "quantity": count})
        total += count

    return out.getvalue(), cards, total


def fetch_precon_decks(user_agent: str) -> tuple[list[PreconDeckEntry], list[str]]:
    """Real data, not a curated list - MTGJSON's own DeckList.json manifest
    filtered to real Commander precons. One commander's deck file failing
    to fetch/parse doesn't abort the rest (same reasoning as
    app.source_adapters.edhrec.fetch_and_synthesize_all) - returns
    (successful entries, error messages for the ones that failed).
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    resp = httpx.get(DECK_LIST_URL, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise SourceFetchError(f"MTGJSON DeckList.json returned HTTP {resp.status_code}")

    all_decks = resp.json().get("data", [])
    commander_entries = [d for d in all_decks if d.get("type") == COMMANDER_DECK_TYPE]
    if not commander_entries:
        raise SourceFetchError("MTGJSON DeckList.json has no 'Commander Deck' entries - page shape may have changed")

    entries: list[PreconDeckEntry] = []
    errors: list[str] = []

    for i, meta in enumerate(commander_entries):
        if i > 0:
            time.sleep(PRECON_REQUEST_DELAY_SECONDS)

        file_name = meta.get("fileName")
        if not file_name:
            continue
        try:
            deck_resp = httpx.get(DECK_URL.format(file_name=file_name), headers=headers, timeout=30)
            if deck_resp.status_code != 200:
                errors.append(f"{file_name}: HTTP {deck_resp.status_code}")
                continue
            data = deck_resp.json().get("data") or {}
            commander_cards = data.get("commander") or []
            main_cards = data.get("mainBoard") or []
            if not commander_cards or not main_cards:
                errors.append(f"{file_name}: missing commander or mainBoard cards")
                continue

            deck_text, cards, total = _build_deck_text(commander_cards, main_cards)
            commander_names = [c.get("name") for c in commander_cards if c.get("name")]

            entries.append(
                PreconDeckEntry(
                    file_name=file_name,
                    name=meta.get("name") or data.get("name") or file_name,
                    commander_names=commander_names,
                    release_date=meta.get("releaseDate"),
                    source_url=meta.get("source") or f"https://mtgjson.com/api/v5/decks/{file_name}.json",
                    card_count=total,
                    cards=cards,
                    deck_text=deck_text,
                )
            )
        except SourceFetchError as exc:
            errors.append(f"{file_name}: {exc}")

    return entries, errors
