"""Budget filter — pure function over already-priced missing-card data, no
DB access (mirrors app.comparison.engine's "plain data in, plain data out"
shape, see ARCHITECTURE.md). Pricing itself (resolving which provider/
currency a card's price comes from) happens in app.services.pricing_service
before this is called — this module only does the greedy allocation once
prices are already known.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PricedMissingCard:
    """One MissingCard (app.comparison.types) plus whatever price
    app.services.pricing_service.resolve_price found for it - unit_price/
    provider are None when no configured provider had a price, never a
    fabricated 0.
    """

    name: str
    oracle_id: str | None
    missing_quantity: int
    unit_price: Decimal | None
    provider: str | None


@dataclass(frozen=True)
class BudgetLine:
    name: str
    oracle_id: str | None
    unit_price: Decimal
    provider: str
    missing_quantity: int
    affordable_quantity: int  # <= missing_quantity - how many copies fit in the budget
    line_total: Decimal  # unit_price * affordable_quantity


@dataclass(frozen=True)
class BudgetResult:
    currency: str
    budget: Decimal
    lines: list[BudgetLine]  # cheapest-first, only cards with a resolvable price
    total_spent: Decimal
    remaining_budget: Decimal
    fully_covered: bool  # every priced card's missing_quantity was fully affordable AND nothing was unpriced
    unpriced: list[PricedMissingCard]  # cards with no resolvable price - can't be budgeted at all


def apply_budget(priced_missing: list[PricedMissingCard], budget: Decimal, currency: str) -> BudgetResult:
    """Greedy cheapest-unit-first allocation: sort priced cards by unit
    price ascending, buy as many copies of each as the remaining budget
    allows before moving to the next. This isn't collection-leverage-aware
    (Phase 7) - it just answers "what does a fixed budget stretch to buy",
    not "which purchases unlock the most buildability".
    """
    priceable = [p for p in priced_missing if p.unit_price is not None]
    unpriced = [p for p in priced_missing if p.unit_price is None]
    priceable_sorted = sorted(priceable, key=lambda p: p.unit_price)  # type: ignore[arg-type,return-value]

    remaining = budget
    lines: list[BudgetLine] = []
    for card in priceable_sorted:
        assert card.unit_price is not None and card.provider is not None
        max_affordable = int(remaining // card.unit_price) if card.unit_price > 0 else card.missing_quantity
        affordable_quantity = min(card.missing_quantity, max(max_affordable, 0))
        line_total = card.unit_price * affordable_quantity
        remaining -= line_total
        lines.append(
            BudgetLine(
                name=card.name,
                oracle_id=card.oracle_id,
                unit_price=card.unit_price,
                provider=card.provider,
                missing_quantity=card.missing_quantity,
                affordable_quantity=affordable_quantity,
                line_total=line_total,
            )
        )

    total_spent = budget - remaining
    fully_covered = not unpriced and all(line.affordable_quantity == line.missing_quantity for line in lines)

    return BudgetResult(
        currency=currency,
        budget=budget,
        lines=lines,
        total_spent=total_spent,
        remaining_budget=remaining,
        fully_covered=fully_covered,
        unpriced=unpriced,
    )
