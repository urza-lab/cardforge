"""Pure set-arithmetic comparison of an owned-card pool against a required-
card list — see README.md "Why no AI": this is deterministic bookkeeping,
not a language problem, so it stays a plain function over plain data.
"""
from __future__ import annotations

from collections.abc import Sequence

from app.comparison.types import ComparisonResult, ComparisonSettings, MissingCard, OwnedCard, RequiredCard


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _oracle_key(card: OwnedCard | RequiredCard) -> str:
    """Group by oracle_id when resolved; fall back to normalized name so
    unresolved cards (e.g. no Scryfall sync has run yet) still compare
    meaningfully instead of being silently excluded.
    """
    return card.oracle_id if card.oracle_id else f"name::{_normalize_name(card.name)}"


def compare(
    owned: Sequence[OwnedCard], required: Sequence[RequiredCard], settings: ComparisonSettings | None = None
) -> ComparisonResult:
    settings = settings or ComparisonSettings()

    owned_pool: dict[str, int] = {}
    if settings.mode == "printing":
        # An unresolved printing can never satisfy an exact-printing
        # requirement — it's not proof of owning any *particular* printing.
        for owned_card in owned:
            if owned_card.scryfall_card_id is None:
                continue
            owned_pool[owned_card.scryfall_card_id] = (
                owned_pool.get(owned_card.scryfall_card_id, 0) + owned_card.quantity
            )
    else:
        for owned_card in owned:
            owned_key = _oracle_key(owned_card)
            owned_pool[owned_key] = owned_pool.get(owned_key, 0) + owned_card.quantity

    missing: list[MissingCard] = []
    total_required_quantity = 0
    total_owned_applied = 0

    for required_card in required:
        total_required_quantity += required_card.quantity

        key: str | None
        if settings.mode == "printing":
            key = required_card.scryfall_card_id
        else:
            key = _oracle_key(required_card)

        available = owned_pool.get(key, 0) if key is not None else 0
        applied = min(available, required_card.quantity)
        total_owned_applied += applied
        shortfall = required_card.quantity - applied

        if shortfall > 0:
            missing.append(
                MissingCard(
                    name=required_card.name,
                    oracle_id=required_card.oracle_id,
                    required_quantity=required_card.quantity,
                    owned_quantity=available,
                    missing_quantity=shortfall,
                    scryfall_card_id=required_card.scryfall_card_id,
                )
            )

        # Decrement the pool so a second required entry with the same key
        # (e.g. two decklist lines for the same card) doesn't double-count
        # the same owned copies.
        if key is not None and key in owned_pool:
            owned_pool[key] = available - applied

    coverage_percent = (
        round(total_owned_applied / total_required_quantity * 100, 2) if total_required_quantity else 100.0
    )

    return ComparisonResult(
        mode=settings.mode,
        total_required_cards=len(required),
        total_required_quantity=total_required_quantity,
        total_owned_quantity=total_owned_applied,
        coverage_percent=coverage_percent,
        is_fully_buildable=not missing,
        missing=missing,
    )
