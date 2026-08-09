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

from app.comparison import ComparisonMode, ComparisonResult, ComparisonSettings, OwnedCard, RequiredCard, compare
from app.models.collection import CollectionItem
from app.parsers import PARSERS
from app.services import scryfall_resolution

# Formats that make sense as "a list of cards to compare against my
# collection" - manabox_csv is collection-export-shaped (condition, price,
# language columns a decklist wouldn't have) and is intentionally excluded.
DECKLIST_SOURCE_TYPES = {"text_list", "json", "generic_csv"}


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

    owned_items = db.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id))
    owned = [
        OwnedCard(
            name=item.card_name,
            quantity=item.quantity,
            oracle_id=item.resolved_oracle_id,
            scryfall_card_id=item.resolved_scryfall_card_id,
        )
        for item in owned_items
    ]

    comparison_mode: ComparisonMode = "printing" if mode == "printing" else "oracle"
    result = compare(owned, required, ComparisonSettings(mode=comparison_mode))
    return ComparisonRun(result=result, row_errors=row_errors)
