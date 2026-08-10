"""Plain-data types for the comparison engine.

No FastAPI/SQLAlchemy-session/HTTP imports anywhere in `app/comparison` (see
ARCHITECTURE.md "The comparison engine is a pure library") — callers (the
API layer, Phase 4's deck/cube pages) build these from ORM rows themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ComparisonMode = Literal["oracle", "printing"]


@dataclass(frozen=True)
class OwnedCard:
    """One entry from a collection, in comparison-ready form."""

    name: str
    quantity: int
    oracle_id: str | None = None
    scryfall_card_id: str | None = None


@dataclass(frozen=True)
class RequiredCard:
    """One entry from the list/deck being compared against a collection."""

    name: str
    quantity: int
    oracle_id: str | None = None
    scryfall_card_id: str | None = None


@dataclass(frozen=True)
class ComparisonSettings:
    mode: ComparisonMode = "oracle"


@dataclass(frozen=True)
class MissingCard:
    name: str
    oracle_id: str | None
    required_quantity: int
    owned_quantity: int
    missing_quantity: int
    # Passed through from the RequiredCard that produced this shortfall,
    # regardless of mode - in printing mode it's the exact printing that was
    # actually unmet; in oracle mode it's whichever printing the requirement
    # happened to resolve to, useful as a starting point for pricing (Phase
    # 6, app/pricing/budget.py) even though oracle-mode matching itself
    # doesn't key on it.
    scryfall_card_id: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    mode: ComparisonMode
    total_required_cards: int  # distinct required entries (decklist lines)
    total_required_quantity: int  # sum of quantities required
    total_owned_quantity: int  # sum of owned quantities actually applied toward requirements
    coverage_percent: float  # 0-100, share of total_required_quantity already covered
    is_fully_buildable: bool
    missing: list[MissingCard] = field(default_factory=list)
