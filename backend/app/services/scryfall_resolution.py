"""Resolves card identity (name / set / collector number / user-supplied
scryfall_id) against the local Scryfall mirror (scryfall_cards).

Used two ways:
- resolve_item / resolve_collection: persist resolved_oracle_id /
  resolved_scryfall_card_id onto CollectionItem rows.
- resolve_card: the same matching logic over plain values, for ad-hoc input
  that isn't a CollectionItem at all — e.g. a decklist pasted into the
  Comparisons page (app/services/comparison_service.py), which is never
  written to the database.

Local-data-only by design: no REST fallback to api.scryfall.com for
individual unresolved cards. Resolving a whole collection or decklist at
once this way, and hitting Scryfall's single-card endpoint per unresolved
row instead, would mean dozens-to-thousands of uncoordinated requests —
exactly what the bulk-data mirror exists to avoid (see SOURCE_ADAPTERS.md
"Rate limits ... enforced centrally, not just best effort"). A REST
single-card lookup belongs in the adapter for a future single-card UI
feature that only ever looks up one card at a time, not here.

Matching priority:
1. scryfall_id (user-supplied) matches a scryfall_cards.id exactly ->
   resolved to that exact printing.
2. set_code + collector_number match -> resolved to that exact printing; if
   multiple language printings share the same number (default_cards
   includes non-English printings), prefer the given language, then
   English, then whatever's left.
3. Name match only (case-insensitive) -> resolves oracle_id (enough for
   oracle-mode comparison) but leaves the exact printing undetermined.
4. No match at all -> both None ("unresolved").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.collection import CollectionItem
from app.models.lists import CardListItem
from app.models.scryfall import ScryfallCard

DEFAULT_LANGUAGE = "en"


@dataclass
class ResolutionSummary:
    total: int
    resolved_exact: int
    resolved_oracle_only: int
    unresolved: int


def _match_by_scryfall_id(db: Session, scryfall_id: str | None) -> ScryfallCard | None:
    if not scryfall_id:
        return None
    return db.get(ScryfallCard, scryfall_id)


def _match_by_set_and_number(
    db: Session, set_code: str | None, collector_number: str | None, language: str | None
) -> ScryfallCard | None:
    if not set_code or not collector_number:
        return None
    stmt = select(ScryfallCard).where(
        ScryfallCard.set_code == set_code.upper(),
        ScryfallCard.collector_number == collector_number,
    )
    candidates = list(db.scalars(stmt))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    preferred_lang = (language or DEFAULT_LANGUAGE).lower()
    for candidate in candidates:
        if candidate.lang.lower() == preferred_lang:
            return candidate
    for candidate in candidates:
        if candidate.lang.lower() == DEFAULT_LANGUAGE:
            return candidate
    return candidates[0]


def _match_oracle_id_by_name(db: Session, name: str) -> str | None:
    # `.ilike(name)` (no wildcards - this is an exact case-insensitive match,
    # not a pattern search) can't use `name`'s plain B-tree index in
    # Postgres, forcing a full sequential scan of all ~530k scryfall_cards
    # rows on every unmatched name - confirmed live (EXPLAIN ANALYZE) at
    # ~865ms worst case *per call*, found while importing a real 450-card
    # CubeCobra cube (many more distinct sets than a typical deck, so many
    # more rows hit this fallback than usual). `func.lower(name) ==
    # name.lower()` instead uses the functional index below
    # (ix_scryfall_cards_name_lower), turning that into an indexed lookup.
    stmt = select(ScryfallCard.oracle_id).where(func.lower(ScryfallCard.name) == name.lower()).limit(1)
    return db.scalar(stmt)


def resolve_card(
    db: Session,
    *,
    name: str,
    set_code: str | None = None,
    collector_number: str | None = None,
    language: str | None = None,
    scryfall_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Returns (oracle_id, scryfall_card_id); either may be None."""
    card = _match_by_scryfall_id(db, scryfall_id) or _match_by_set_and_number(
        db, set_code, collector_number, language
    )
    if card is not None:
        return card.oracle_id, card.id
    return _match_oracle_id_by_name(db, name), None


# CollectionItem and CardListItem have the same identity/resolution columns
# by design (see app/models/lists.py), so one function resolves either. A
# structural Protocol looked cleaner but mypy doesn't match SQLAlchemy's
# Mapped[...] descriptors against plain-typed Protocol members - an explicit
# Union is what actually type-checks.
ResolvableItem = CollectionItem | CardListItem


def resolve_item(db: Session, item: ResolvableItem) -> None:
    """Mutates `item` in place (resolved_oracle_id / resolved_scryfall_card_id
    / resolved_at). Does not commit — callers batch-commit after resolving
    however many items they're touching.
    """
    oracle_id, scryfall_card_id = resolve_card(
        db,
        name=item.card_name,
        set_code=item.set_code,
        collector_number=item.collector_number,
        language=item.language,
        scryfall_id=item.scryfall_id,
    )
    item.resolved_oracle_id = oracle_id
    item.resolved_scryfall_card_id = scryfall_card_id
    item.resolved_at = datetime.now(UTC)


def resolve_collection(db: Session, collection_id: int) -> ResolutionSummary:
    """Re-resolve every item in a collection (e.g. after a fresh Scryfall
    sync) and commit once at the end.
    """
    stmt = select(CollectionItem).where(CollectionItem.collection_id == collection_id)
    items = list(db.scalars(stmt))

    resolved_exact = 0
    resolved_oracle_only = 0
    unresolved = 0
    for item in items:
        resolve_item(db, item)
        if item.resolved_scryfall_card_id:
            resolved_exact += 1
        elif item.resolved_oracle_id:
            resolved_oracle_only += 1
        else:
            unresolved += 1

    db.commit()
    return ResolutionSummary(
        total=len(items),
        resolved_exact=resolved_exact,
        resolved_oracle_only=resolved_oracle_only,
        unresolved=unresolved,
    )
