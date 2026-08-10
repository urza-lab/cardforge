"""Scryfall bulk-data adapter: downloads and locally mirrors Scryfall's
"all_cards" bulk export (one row per printing *and* per language,
gzip-compressed JSONL) into `scryfall_cards`. See SOURCE_ADAPTERS.md for the
adapter table entry and QUICKSTART.md for the
CARDFORGE_SCRYFALL_BULK_AUTO_DOWNLOAD behavior this implements.

`all_cards`, not the smaller `default_cards` (Phase 3's original choice) —
see app.models.scryfall module docstring for why (localized `printed_name`
availability, Phase 4). Substantially bigger: several hundred MB compressed
and a few times the row count of `default_cards`, vs. `default_cards`'
110k rows / ~77MB.

Deliberately *not* the generic `SourceAdapter` protocol from
SOURCE_ADAPTERS.md — that shape (validate_url/fetch_by_url/search/parse) is
for per-list adapters (Moxfield, Archidekt, Phase 5). A one-file bulk mirror
sync doesn't fit it; this module is its own small thing.
"""
from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.pricing import PriceObservation, PriceProvider
from app.models.scryfall import SYNC_STATE_ID, ScryfallCard, ScryfallSyncState, ScryfallSyncStatus

log = logging.getLogger("cardforge.scryfall")

BULK_DATA_API = "https://api.scryfall.com/bulk-data"
BULK_DATA_TYPE = "all_cards"
BATCH_SIZE = 2000
# all_cards is a few hundred MB - more generous than a "just don't hang
# forever" default_cards timeout would need.
DOWNLOAD_TIMEOUT_SECONDS = 600

# Layouts that aren't "a printing a collector owns" in any sense CardForge's
# collection/comparison features care about.
_EXCLUDED_LAYOUTS = {"art_series", "double_faced_token", "emblem", "scheme", "vanguard", "token"}


class ScryfallSyncError(RuntimeError):
    pass


def _headers(settings: Settings) -> dict[str, str]:
    return {"User-Agent": settings.scryfall_user_agent, "Accept": "application/json"}


def fetch_bulk_manifest(settings: Settings) -> dict[str, Any]:
    resp = httpx.get(BULK_DATA_API, headers=_headers(settings), timeout=30)
    resp.raise_for_status()
    for entry in resp.json()["data"]:
        if entry["type"] == BULK_DATA_TYPE:
            return entry  # type: ignore[no-any-return]
    raise ScryfallSyncError(f"bulk-data manifest has no '{BULK_DATA_TYPE}' entry")


def download_bulk_file(download_uri: str, dest_path: Path, settings: Settings) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".part")
    with httpx.stream(
        "GET", download_uri, headers=_headers(settings), timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
    ) as resp:
        resp.raise_for_status()
        with tmp_path.open("wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp_path.replace(dest_path)  # atomic on the same filesystem - never leaves a half-written cache file


def iter_cards_from_file(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def _map_card(data: dict[str, Any]) -> dict[str, Any] | None:
    layout = data.get("layout", "")
    if layout in _EXCLUDED_LAYOUTS:
        return None

    oracle_text = data.get("oracle_text")
    mana_cost = data.get("mana_cost")
    colors = data.get("colors")
    printed_name = data.get("printed_name")
    faces = data.get("card_faces")
    if faces:
        if oracle_text is None:
            face_texts = [f.get("oracle_text") for f in faces if f.get("oracle_text")]
            oracle_text = " // ".join(face_texts) if face_texts else None
        if not mana_cost:
            face_costs = [f.get("mana_cost") for f in faces if f.get("mana_cost")]
            mana_cost = " // ".join(face_costs) if face_costs else None
        if colors is None:
            colors = faces[0].get("colors")
        if printed_name is None:
            face_printed_names = [f.get("printed_name") for f in faces if f.get("printed_name")]
            printed_name = " // ".join(face_printed_names) if face_printed_names else None

    return {
        "id": data["id"],
        "oracle_id": data.get("oracle_id", data["id"]),  # some reversible layouts share one oracle_id
        "name": data["name"],
        "printed_name": printed_name,
        "set_code": data["set"].upper(),
        "set_name": data.get("set_name", ""),
        "collector_number": data.get("collector_number", ""),
        "lang": data.get("lang", "en"),
        "layout": layout,
        "mana_cost": mana_cost,
        "cmc": data.get("cmc"),
        "type_line": data.get("type_line"),
        "oracle_text": oracle_text,
        "colors": colors,
        "color_identity": data.get("color_identity"),
        "rarity": data.get("rarity"),
        "foil": bool(data.get("foil", False)),
        "nonfoil": bool(data.get("nonfoil", False)),
        "released_at": data.get("released_at"),
    }


# Scryfall's own "prices" object has usd/usd_foil/usd_etched/eur/eur_foil/
# eur_etched/tix keys - only the four most broadly useful ones are mirrored
# (see PRICING.md); etched and MTGO "tix" are niche enough to skip rather
# than add two more currencies/finishes nothing reads yet.
_PRICE_FIELDS = (("usd", "USD", False), ("usd_foil", "USD", True), ("eur", "EUR", False), ("eur_foil", "EUR", True))


def _map_prices(data: dict[str, Any]) -> list[dict[str, Any]]:
    prices = data.get("prices") or {}
    rows: list[dict[str, Any]] = []
    for key, currency, foil in _PRICE_FIELDS:
        raw_price = prices.get(key)
        if raw_price is None:
            continue
        try:
            price = Decimal(raw_price)
        except InvalidOperation:
            continue
        rows.append(
            {
                "scryfall_card_id": data["id"],
                "provider": PriceProvider.scryfall.value,
                "currency": currency,
                "foil": foil,
                "price": price,
            }
        )
    return rows


def run_bulk_sync(db: Session, settings: Settings | None = None) -> ScryfallSyncState:
    """Download, parse, and replace the local scryfall_cards mirror.

    The old rows are only deleted once the new data is fully parsed and
    ready to insert, all inside one transaction that only commits at the
    very end — a failure at any point before that rolls back cleanly and
    leaves the previous successful sync's data untouched (see
    ARCHITECTURE.md "no fake success": a sync that didn't finish must never
    look like it did, and must never wipe out data that did finish).

    Also (Phase 6) extracts each card's own `prices` into
    `price_observations` (provider="scryfall") in the same pass - no extra
    download needed. `price_observations.scryfall_card_id` has `ON DELETE
    CASCADE` to `scryfall_cards.id`, so the `delete(ScryfallCard)` below
    would silently wipe *every* provider's prices (manual entries included)
    even though the same IDs get reinserted moments later in this same
    transaction - non-scryfall rows are snapshotted before the delete and
    restored after, for any printing ID still present in the new data (see
    PRICING.md).
    """
    settings = settings or get_settings()
    state = db.get(ScryfallSyncState, SYNC_STATE_ID)
    if state is None:
        raise ScryfallSyncError("scryfall_sync_state row is missing - has the migration been applied?")

    state.status = ScryfallSyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        manifest = fetch_bulk_manifest(settings)
        cache_path = Path(settings.scryfall_cache_dir) / "all_cards.jsonl.gz"
        download_bulk_file(manifest["jsonl_download_uri"], cache_path, settings)

        preserved_prices = [
            {
                "scryfall_card_id": row.scryfall_card_id,
                "provider": row.provider,
                "currency": row.currency,
                "foil": row.foil,
                "price": row.price,
            }
            for row in db.scalars(
                select(PriceObservation).where(PriceObservation.provider != PriceProvider.scryfall.value)
            )
        ]

        db.execute(delete(ScryfallCard))
        seen_ids: set[str] = set()
        count = 0
        batch: list[dict[str, Any]] = []
        price_batch: list[dict[str, Any]] = []
        for raw in iter_cards_from_file(cache_path):
            mapped = _map_card(raw)
            if mapped is None:
                continue
            seen_ids.add(mapped["id"])
            batch.append(mapped)
            price_batch.extend(_map_prices(raw))
            count += 1
            # Flushed together, cards first - a price row's card must exist
            # in the DB before that row can be inserted (FK). Each card
            # contributes up to 4 price rows but only 1 card row, so
            # price_batch reaches BATCH_SIZE well before batch does on its
            # own; triggering off either one and always flushing batch
            # first is what keeps every price insert's FK satisfied (a real
            # ForeignKeyViolation this fixed, found against a real sync).
            if len(batch) >= BATCH_SIZE or len(price_batch) >= BATCH_SIZE:
                db.execute(insert(ScryfallCard), batch)
                batch = []
                if price_batch:
                    db.execute(insert(PriceObservation), price_batch)
                    price_batch = []
        if batch:
            db.execute(insert(ScryfallCard), batch)
        if price_batch:
            db.execute(insert(PriceObservation), price_batch)

        restorable = [p for p in preserved_prices if p["scryfall_card_id"] in seen_ids]
        if restorable:
            db.execute(insert(PriceObservation), restorable)
        dropped = len(preserved_prices) - len(restorable)
        if dropped:
            log.warning(
                "scryfall bulk sync: dropped %d non-scryfall price observation(s) for printings no "
                "longer in the mirror",
                dropped,
            )

        state.status = ScryfallSyncStatus.current.value
        state.bulk_data_type = BULK_DATA_TYPE
        state.source_updated_at = datetime.fromisoformat(manifest["updated_at"])
        state.card_count = count
        state.finished_at = datetime.now(UTC)
        db.commit()
        log.info("scryfall bulk sync complete: %d cards", count)
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = db.get(ScryfallSyncState, SYNC_STATE_ID)
        assert state is not None
        state.status = ScryfallSyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        log.exception("scryfall bulk sync failed")
        raise

    return state
