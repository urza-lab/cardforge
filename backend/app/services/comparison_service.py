"""Ad-hoc, non-persisted comparison: parse a decklist input the same way
Phase 2 parses collection imports, resolve each line against the local
Scryfall mirror without writing anything to the database, and run it
through the pure comparison engine (app/comparison) against a collection's
already-resolved items.

Deliberately not modeled after the import pipeline's preview/confirm/abort
dance (IMPORT_FORMATS.md): that ceremony exists because confirming an import
writes to the collection. A comparison is read-only and throwaway — parse,
resolve, compare, respond, done in one request.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comparison import (
    ComparisonMode,
    ComparisonResult,
    ComparisonSettings,
    OwnedCard,
    RequiredCard,
    compare,
)
from app.models.collection import CollectionItem
from app.models.lists import CardListItem
from app.parsers import PARSERS
from app.services import scryfall_resolution

# Formats that make sense as "a list of cards to compare against my
# collection" - manabox_csv is collection-export-shaped (condition, price,
# language columns a decklist wouldn't have) and is intentionally excluded.
DECKLIST_SOURCE_TYPES = {"text_list", "json", "generic_csv"}

# Sections counted as "needed to build this list" for a saved CardList
# comparison (see app/models/lists.py ListItemSection). sideboard/maybeboard/
# considering are explicitly optional/exploratory, not part of "is this
# buildable" — README.md scopes CardForge around Commander decks and cubes,
# which don't have a required sideboard the way constructed formats do.
REQUIRED_LIST_SECTIONS = {"mainboard", "commander", "companion"}


class UnsupportedSourceTypeError(ValueError):
    pass


class InvalidComparisonModeError(ValueError):
    pass


@dataclass
class ComparisonRowError:
    row_number: int
    raw: dict[str, Any]
    error: str


@dataclass
class ComparisonRun:
    result: ComparisonResult
    row_errors: list[ComparisonRowError] = field(default_factory=list)


def run_comparison(
    db: Session,
    *,
    collection_id: int,
    source_type: str,
    content: str,
    mode: str = "oracle",
    column_mapping: dict[str, str] | None = None,
) -> ComparisonRun:
    if source_type not in DECKLIST_SOURCE_TYPES:
        raise UnsupportedSourceTypeError(
            f"unsupported decklist source_type '{source_type}', expected one of {sorted(DECKLIST_SOURCE_TYPES)}"
        )
    if mode not in ("oracle", "printing"):
        raise InvalidComparisonModeError(f"mode must be 'oracle' or 'printing', got '{mode}'")

    parser = PARSERS[source_type]
    kwargs: dict[str, Any] = {"column_mapping": column_mapping} if source_type == "generic_csv" else {}
    parse_result = parser(content, **kwargs)

    required: list[RequiredCard] = []
    row_errors: list[ComparisonRowError] = []
    for row in parse_result.rows:
        if row.mapped is None:
            row_errors.append(
                ComparisonRowError(row_number=row.row_number, raw=row.raw, error=row.error or "unknown error")
            )
            continue
        oracle_id, scryfall_card_id = scryfall_resolution.resolve_card(
            db,
            name=row.mapped["name"],
            set_code=row.mapped["set_code"],
            collector_number=row.mapped["collector_number"],
            language=row.mapped["language"],
            scryfall_id=row.mapped["scryfall_id"],
        )
        required.append(
            RequiredCard(
                name=row.mapped["name"],
                quantity=row.mapped["quantity"],
                oracle_id=oracle_id,
                scryfall_card_id=scryfall_card_id,
            )
        )

    owned = _owned_cards(db, collection_id)
    comparison_mode: ComparisonMode = "printing" if mode == "printing" else "oracle"
    result = compare(owned, required, ComparisonSettings(mode=comparison_mode))
    return ComparisonRun(result=result, row_errors=row_errors)


def _owned_cards(db: Session, collection_id: int) -> list[OwnedCard]:
    owned_items = db.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id))
    return [
        OwnedCard(
            name=item.card_name,
            quantity=item.quantity,
            oracle_id=item.resolved_oracle_id,
            scryfall_card_id=item.resolved_scryfall_card_id,
        )
        for item in owned_items
    ]


def _required_cards_for_lists(db: Session, list_ids: list[int]) -> list[RequiredCard]:
    required: list[RequiredCard] = []
    for chunk in _chunked_ids(list_ids):
        list_items = db.scalars(
            select(CardListItem).where(
                CardListItem.list_id.in_(chunk), CardListItem.section.in_(REQUIRED_LIST_SECTIONS)
            )
        )
        required.extend(
            RequiredCard(
                name=item.card_name,
                quantity=item.quantity,
                oracle_id=item.resolved_oracle_id,
                scryfall_card_id=item.resolved_scryfall_card_id,
            )
            for item in list_items
        )
    return required


# Postgres hard-caps a single query at 65535 bound parameters - an IN(...)
# clause built directly from every list_id in the collection can exceed
# that once the real list count grows large enough (confirmed live: the
# 2026-08-19 full CubeCobra import pushed the real collection past 82,000
# lists and made this exact query fail outright with "number of parameters
# must be between 0 and 65535", breaking both the Dashboard and every
# Prometheus /metrics scrape - see CLAUDE.md gotcha #33 for the same
# ceiling hit once before on a different IN clause). Chunking well under
# the ceiling keeps every batch safe regardless of how large the real list
# count grows.
_LIST_ID_CHUNK_SIZE = 5000


def _chunked_ids(ids: list[int], size: int = _LIST_ID_CHUNK_SIZE) -> Iterator[list[int]]:
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def required_cards_by_list(db: Session, list_ids: list[int]) -> dict[int, list[RequiredCard]]:
    """Same rows as `_required_cards_for_lists`, grouped by list_id - one
    query for every list combined instead of one query per list. Callers
    that need each list's own required cards separately (e.g.
    app.metrics.dashboard_service.compute_list_buildability, called on
    every dashboard load *and* every Prometheus scrape) used to call
    `_required_cards_for_lists(db, [single_id])` in a loop - an N+1 query
    pattern invisible at a "household with dozens of decks/cubes" scale
    (see app/comparison/leverage.py's own note on that assumption) but
    confirmed live to take ~11s once real usage pushed a real collection
    past 500 lists (a bulk "select all" cube import - see CLAUDE.md).
    """
    grouped: dict[int, list[RequiredCard]] = {list_id: [] for list_id in list_ids}
    for chunk in _chunked_ids(list_ids):
        # Plain columns, not full CardListItem ORM entities - at real scale
        # (hundreds of lists, hundreds of thousands of rows) hydrating a full
        # mapped object per row is itself the dominant cost of this function,
        # confirmed live to take ~8s on its own even after this was already
        # one query instead of one-per-list (see CLAUDE.md) - a plain tuple
        # row needs no identity-map/relationship bookkeeping.
        rows = db.execute(
            select(
                CardListItem.list_id,
                CardListItem.card_name,
                CardListItem.quantity,
                CardListItem.resolved_oracle_id,
                CardListItem.resolved_scryfall_card_id,
            ).where(CardListItem.list_id.in_(chunk), CardListItem.section.in_(REQUIRED_LIST_SECTIONS))
        )
        for list_id, card_name, quantity, oracle_id, scryfall_card_id in rows:
            grouped[list_id].append(
                RequiredCard(
                    name=card_name, quantity=quantity, oracle_id=oracle_id, scryfall_card_id=scryfall_card_id
                )
            )
    return grouped


def run_list_comparison(
    db: Session, *, list_id: int, collection_id: int, mode: str = "oracle"
) -> ComparisonResult:
    """Compare a saved CardList's mainboard/commander/companion items
    against a collection's already-resolved items. Unlike run_comparison
    above, there's no parsing step (the list is already persisted and
    resolved) — just the required/owned build and the pure engine call.
    """
    if mode not in ("oracle", "printing"):
        raise InvalidComparisonModeError(f"mode must be 'oracle' or 'printing', got '{mode}'")

    required = _required_cards_for_lists(db, [list_id])
    owned = _owned_cards(db, collection_id)
    comparison_mode: ComparisonMode = "printing" if mode == "printing" else "oracle"
    return compare(owned, required, ComparisonSettings(mode=comparison_mode))


def run_shopping_list(
    db: Session, *, list_ids: list[int], collection_id: int, mode: str = "oracle"
) -> ComparisonResult:
    """Same idea as run_list_comparison but across several lists at once,
    compared against ONE shared owned pool in a single compare() call - not
    N independent comparisons summed together. That distinction matters: if
    two decks each want 1 copy of a card you own exactly 1 of, summing two
    independent "you have it" comparisons would double-count that copy and
    under-report what you actually need to buy. Feeding every list's
    required cards into one compare() call lets the engine's owned-pool
    decrement (see app/comparison/engine.py) account for that copy being
    claimed by whichever list's requirement is processed first.
    """
    if mode not in ("oracle", "printing"):
        raise InvalidComparisonModeError(f"mode must be 'oracle' or 'printing', got '{mode}'")

    required = _required_cards_for_lists(db, list_ids)
    owned = _owned_cards(db, collection_id)
    comparison_mode: ComparisonMode = "printing" if mode == "printing" else "oracle"
    return compare(owned, required, ComparisonSettings(mode=comparison_mode))
