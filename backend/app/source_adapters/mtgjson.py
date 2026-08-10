"""MTGJSON price provider — see PRICING.md. Downloads MTGJSON's own daily
price snapshot (`AllPricesToday.json`, real retail prices sourced from
TCGplayer and Cardmarket) plus its identifiers file (`AllIdentifiers.json.xz`
— needed because MTGJSON's own card UUIDs are a different ID space than
Scryfall's; `identifiers.scryfallId` is the join key) and mirrors USD
(tcgplayer retail) / EUR (cardmarket retail) prices into
`price_observations`, provider="mtgjson".

Two real downloads, verified live during development: `AllIdentifiers.json.xz`
(~110MB compressed / ~630MB decompressed — a single JSON object, not
line-delimited like Scryfall's bulk export, so it's parsed in one shot
rather than streamed) and `AllPricesToday.json` (~50MB, today's snapshot
only — no price history, matching `price_observations`' "latest value"
shape). This is the real technical source for CardForge's Cardmarket price
data too — see SOURCE_ADAPTERS.md for why there's no separate direct
Cardmarket-API adapter.
"""
from __future__ import annotations

import json
import logging
import lzma
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.pricing import PriceObservation, PriceProvider, PriceSyncState, PriceSyncStatus
from app.models.scryfall import ScryfallCard

log = logging.getLogger("cardforge.mtgjson")

IDENTIFIERS_URL = "https://mtgjson.com/api/v5/AllIdentifiers.json.xz"
PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json"
DOWNLOAD_TIMEOUT_SECONDS = 300
BATCH_SIZE = 2000


class MtgjsonSyncError(RuntimeError):
    pass


def _headers(settings: Settings) -> dict[str, str]:
    return {"User-Agent": settings.scryfall_user_agent, "Accept": "application/json"}


def fetch_identifiers_map(settings: Settings) -> dict[str, str]:
    """mtgjson uuid -> scryfall id, for every card MTGJSON has a Scryfall ID
    for (a small minority of very obscure entries don't have one - skipped,
    never defaulted to anything).
    """
    resp = httpx.get(IDENTIFIERS_URL, headers=_headers(settings), timeout=DOWNLOAD_TIMEOUT_SECONDS)
    resp.raise_for_status()
    decompressed = lzma.decompress(resp.content)
    data = json.loads(decompressed)
    mapping: dict[str, str] = {}
    for mtgjson_uuid, card in data["data"].items():
        scryfall_id = card.get("identifiers", {}).get("scryfallId")
        if scryfall_id:
            mapping[mtgjson_uuid] = scryfall_id
    return mapping


def fetch_prices_today(settings: Settings) -> dict[str, Any]:
    resp = httpx.get(PRICES_URL, headers=_headers(settings), timeout=DOWNLOAD_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()["data"]


def _latest(date_map: dict[str, Any] | None) -> Any | None:
    """Each price leaf is `{"<date>": <value>}` — the "Today" snapshot has
    exactly one date key in practice, but take the max date defensively
    rather than assuming that always holds.
    """
    if not date_map:
        return None
    return date_map[max(date_map)]


def _map_prices(scryfall_id: str, card_prices: dict[str, Any]) -> list[dict[str, Any]]:
    paper = card_prices.get("paper") or {}  # digital-only cards (Arena/MTGO) have no "paper" key
    rows: list[dict[str, Any]] = []

    for source, currency in (("tcgplayer", "USD"), ("cardmarket", "EUR")):
        retail = (paper.get(source) or {}).get("retail") or {}
        for key, foil in (("normal", False), ("foil", True)):
            raw_price = _latest(retail.get(key))
            if raw_price is None:
                continue
            try:
                price = Decimal(str(raw_price))
            except InvalidOperation:
                continue
            rows.append(
                {
                    "scryfall_card_id": scryfall_id,
                    "provider": PriceProvider.mtgjson.value,
                    "currency": currency,
                    "foil": foil,
                    "price": price,
                }
            )
    return rows


def run_price_sync(db: Session, settings: Settings | None = None) -> PriceSyncState:
    """Download, join, and replace the mtgjson-provider rows in
    price_observations. Only `scryfall_card_id`s already present in our
    scryfall_cards mirror are written (the FK requires it, and a price for
    a printing outside the mirror couldn't be resolved against it anyway) —
    a printing MTGJSON prices but our own Scryfall mirror doesn't (yet)
    know about is silently skipped, not an error.
    """
    settings = settings or get_settings()
    state = db.get(PriceSyncState, PriceProvider.mtgjson.value)
    if state is None:
        raise MtgjsonSyncError("price_sync_state row for 'mtgjson' is missing - has the migration been applied?")

    state.status = PriceSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        identifiers_map = fetch_identifiers_map(settings)
        prices_data = fetch_prices_today(settings)
        existing_ids = {row[0] for row in db.execute(select(ScryfallCard.id))}

        # More than one mtgjson uuid can map to the same scryfallId (found
        # against real data: MTGJSON tracks some promos/variations as
        # distinct entries that nonetheless share a Scryfall printing ID) -
        # `price_observations` has one row per (card, provider, currency,
        # foil), so rows are deduplicated by that key before inserting
        # (last-write-wins) instead of letting the unique constraint reject
        # the whole batch. Collected in memory first, not streamed straight
        # to inserts, specifically so a duplicate discovered late doesn't
        # invalidate rows already flushed in an earlier batch.
        rows_by_key: dict[tuple[str, str, bool], dict[str, Any]] = {}
        for mtgjson_uuid, card_prices in prices_data.items():
            scryfall_id = identifiers_map.get(mtgjson_uuid)
            if scryfall_id is None or scryfall_id not in existing_ids:
                continue
            for row in _map_prices(scryfall_id, card_prices):
                rows_by_key[(row["scryfall_card_id"], row["currency"], row["foil"])] = row

        db.execute(delete(PriceObservation).where(PriceObservation.provider == PriceProvider.mtgjson.value))
        count = 0
        batch: list[dict[str, Any]] = []
        for row in rows_by_key.values():
            batch.append(row)
            count += 1
            if len(batch) >= BATCH_SIZE:
                db.execute(insert(PriceObservation), batch)
                batch = []
        if batch:
            db.execute(insert(PriceObservation), batch)

        state.status = PriceSyncStatus.current.value
        state.price_count = count
        state.finished_at = datetime.now(UTC)
        db.commit()
        log.info("mtgjson price sync complete: %d price observations", count)
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = db.get(PriceSyncState, PriceProvider.mtgjson.value)
        assert state is not None
        state.status = PriceSyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        log.exception("mtgjson price sync failed")
        raise

    return state
