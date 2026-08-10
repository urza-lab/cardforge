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
    list_items = db.scalars(
        select(CardListItem).where(
            CardListItem.list_id.in_(list_ids), CardListItem.section.in_(REQUIRED_LIST_SECTIONS)
        )
    )
    return [
        RequiredCard(
            name=item.card_name,
            quantity=item.quantity,
            oracle_id=item.resolved_oracle_id,
            scryfall_card_id=item.resolved_scryfall_card_id,
        )
        for item in list_items
    ]


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
