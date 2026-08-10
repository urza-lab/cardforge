"""Collection leverage (Phase 7) — "which purchase unlocks the most
additional buildability" (README.md). A pure function over the same plain
data `app.comparison.engine.compare` already works with, so it stays part
of the pure comparison engine (see ARCHITECTURE.md "The comparison engine
is a pure library") rather than living in `app/services/` or `app/metrics/`
— it's a what-if extension of `compare`, not DB orchestration.

The metric: for each card missing from at least one list, simulate
acquiring exactly enough copies to fully cover its aggregate shortfall
across every list (the same pooled owned-pool decrement `compare` already
does for the shopping list, see `engine.py`), then measure how many lists
newly become fully buildable and how much total coverage improves. Ranked
by lists-newly-buildable first (a card that single-handedly completes two
decks matters more than one that nudges five decks' coverage a little),
total coverage gain as the tiebreaker. Not price-aware on its own — see
`app/services/dashboard_service.py` for how a caller can combine this with
`app.pricing` to rank by leverage-per-dollar instead.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.comparison.engine import compare
from app.comparison.types import ComparisonSettings, MissingCard, OwnedCard, RequiredCard


@dataclass(frozen=True)
class LeverageCandidate:
    name: str
    oracle_id: str | None
    scryfall_card_id: str | None
    quantity_needed: int  # copies to acquire to fully cover this candidate's aggregate shortfall
    lists_newly_buildable: int
    total_coverage_gain: float  # sum, across every list, of coverage_percent point increase


def _candidate_key(missing: MissingCard, mode: str) -> str:
    """Groups MissingCard entries the same way engine.py's owned-pool
    lookup does: printing mode keys on the exact printing, oracle mode on
    oracle_id (falling back to normalized name for unresolved cards) - see
    `app.comparison.engine._oracle_key`. Needed because `compare()` emits
    one MissingCard *per required-card line*, not merged across lines that
    happen to want the same card (e.g. two decks each listing "1 Sol
    Ring") - without this grouping, the same card would appear as two
    separate half-sized candidates instead of one full-sized one.
    """
    if mode == "printing" and missing.scryfall_card_id:
        return missing.scryfall_card_id
    if missing.oracle_id:
        return missing.oracle_id
    return f"name::{' '.join(missing.name.strip().lower().split())}"


def compute_leverage(
    owned: Sequence[OwnedCard],
    lists_required: Mapping[Any, Sequence[RequiredCard]],
    settings: ComparisonSettings | None = None,
) -> list[LeverageCandidate]:
    settings = settings or ComparisonSettings()
    if not lists_required:
        return []

    baseline = {key: compare(owned, required, settings) for key, required in lists_required.items()}

    # One pooled compare() over every list's requirements combined gives the
    # correctly-decremented aggregate shortfall per card - exactly the same
    # "don't double-count a copy two lists both want" logic
    # comparison_service.run_shopping_list relies on (see engine.py). Still
    # needs grouping below since compare() doesn't merge same-card lines
    # from different required-card entries on its own.
    all_required = [card for required in lists_required.values() for card in required]
    pooled = compare(owned, all_required, settings)

    grouped: dict[str, MissingCard] = {}
    for missing in pooled.missing:
        key = _candidate_key(missing, settings.mode)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = missing
        else:
            grouped[key] = MissingCard(
                name=existing.name,
                oracle_id=existing.oracle_id,
                required_quantity=existing.required_quantity + missing.required_quantity,
                owned_quantity=existing.owned_quantity,
                missing_quantity=existing.missing_quantity + missing.missing_quantity,
                scryfall_card_id=existing.scryfall_card_id,
            )

    candidates: list[LeverageCandidate] = []
    for missing in grouped.values():
        extra = OwnedCard(
            name=missing.name,
            quantity=missing.missing_quantity,
            oracle_id=missing.oracle_id,
            scryfall_card_id=missing.scryfall_card_id,
        )
        hypothetical_owned = [*owned, extra]

        lists_newly_buildable = 0
        total_coverage_gain = 0.0
        for key, required in lists_required.items():
            after = compare(hypothetical_owned, required, settings)
            before = baseline[key]
            if after.is_fully_buildable and not before.is_fully_buildable:
                lists_newly_buildable += 1
            total_coverage_gain += after.coverage_percent - before.coverage_percent

        candidates.append(
            LeverageCandidate(
                name=missing.name,
                oracle_id=missing.oracle_id,
                scryfall_card_id=missing.scryfall_card_id,
                quantity_needed=missing.missing_quantity,
                lists_newly_buildable=lists_newly_buildable,
                total_coverage_gain=round(total_coverage_gain, 2),
            )
        )

    candidates.sort(key=lambda c: (c.lists_newly_buildable, c.total_coverage_gain), reverse=True)
    return candidates
