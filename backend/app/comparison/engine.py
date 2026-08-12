"""Pure set-arithmetic comparison of an owned-card pool against a required-
card list — see README.md "Why no AI": this is deterministic bookkeeping,
not a language problem, so it stays a plain function over plain data.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.comparison.types import ComparisonResult, ComparisonSettings, MissingCard, OwnedCard, RequiredCard


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _oracle_key(card: OwnedCard | RequiredCard) -> str:
    """Group by oracle_id when resolved; fall back to normalized name so
    unresolved cards (e.g. no Scryfall sync has run yet) still compare
    meaningfully instead of being silently excluded.
    """
    return card.oracle_id if card.oracle_id else f"name::{_normalize_name(card.name)}"


def build_owned_pool(owned: Sequence[OwnedCard], mode: str) -> dict[str, int]:
    """The key->quantity pool `compare_pool` reads from (never mutates -
    see its own docstring), split out so a caller that runs many
    compare()s against the *same* owned cards in a tight loop
    (app.comparison.leverage) can build it once instead of paying this
    function's full owned-list scan on every call.
    """
    owned_pool: dict[str, int] = {}
    if mode == "printing":
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
    return owned_pool


def compare_pool(
    owned_pool: Mapping[str, int], required: Sequence[RequiredCard], settings: ComparisonSettings | None = None
) -> ComparisonResult:
    """Same result `compare()` would produce for the owned cards
    `owned_pool` was built from (see `build_owned_pool`) - but treats
    `owned_pool` as read-only and never mutates or copies it. Per-key
    consumption within this one call (needed so two required lines for the
    same card don't double-count the same owned copies) is tracked in a
    small local dict scoped to just the keys `required` actually touches,
    not the full pool - this is what lets a caller running many compare()s
    against the *same* owned pool in a tight loop (app.comparison.leverage,
    called once per list per candidate card) skip both the O(len(owned))
    pool-rebuild *and* an O(len(owned)) `dict.copy()` on every call and pay
    only O(len(required)) instead - confirmed live to matter once real
    usage pushed list counts into the hundreds (see CLAUDE.md).
    """
    settings = settings or ComparisonSettings()
    missing: list[MissingCard] = []
    total_required_quantity = 0
    total_owned_applied = 0
    consumed: dict[str, int] = {}

    for required_card in required:
        total_required_quantity += required_card.quantity

        key: str | None = required_card.scryfall_card_id if settings.mode == "printing" else _oracle_key(required_card)

        already_used = consumed.get(key, 0) if key is not None else 0
        available = max((owned_pool.get(key, 0) if key is not None else 0) - already_used, 0)
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

        if key is not None and applied > 0:
            consumed[key] = already_used + applied

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


def compare(
    owned: Sequence[OwnedCard], required: Sequence[RequiredCard], settings: ComparisonSettings | None = None
) -> ComparisonResult:
    settings = settings or ComparisonSettings()
    owned_pool = build_owned_pool(owned, settings.mode)
    return compare_pool(owned_pool, required, settings)
