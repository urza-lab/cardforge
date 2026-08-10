from __future__ import annotations

from decimal import Decimal

from app.pricing.budget import PricedMissingCard, apply_budget


def _card(name: str, price: Decimal | None, qty: int, provider: str | None = "manual") -> PricedMissingCard:
    return PricedMissingCard(name=name, oracle_id=None, missing_quantity=qty, unit_price=price, provider=provider)


def test_apply_budget_fully_covers_when_budget_is_generous():
    priced = [_card("Sol Ring", Decimal("2.00"), 1), _card("Lightning Bolt", Decimal("1.00"), 4)]
    result = apply_budget(priced, Decimal("100.00"), "USD")

    assert result.fully_covered is True
    assert result.total_spent == Decimal("6.00")  # 2*1 + 1*4
    assert result.remaining_budget == Decimal("94.00")
    assert result.unpriced == []


def test_apply_budget_buys_cheapest_first_and_stops():
    priced = [_card("Expensive", Decimal("50.00"), 1), _card("Cheap", Decimal("1.00"), 10)]
    result = apply_budget(priced, Decimal("5.00"), "USD")

    by_name = {line.name: line for line in result.lines}
    assert by_name["Cheap"].affordable_quantity == 5  # cheapest bought first, all budget spent here
    assert by_name["Expensive"].affordable_quantity == 0
    assert result.total_spent == Decimal("5.00")
    assert result.remaining_budget == Decimal("0.00")
    assert result.fully_covered is False


def test_apply_budget_partial_quantity_within_one_card():
    priced = [_card("Sol Ring", Decimal("3.00"), 5)]
    result = apply_budget(priced, Decimal("10.00"), "USD")

    assert result.lines[0].affordable_quantity == 3  # floor(10/3)
    assert result.lines[0].line_total == Decimal("9.00")
    assert result.remaining_budget == Decimal("1.00")
    assert result.fully_covered is False


def test_apply_budget_separates_unpriced_cards():
    priced = [_card("Priced", Decimal("1.00"), 1), _card("No Price Available", None, 2, provider=None)]
    result = apply_budget(priced, Decimal("100.00"), "USD")

    assert len(result.lines) == 1
    assert len(result.unpriced) == 1
    assert result.unpriced[0].name == "No Price Available"
    assert result.fully_covered is False  # unpriced cards block "fully covered" even with plenty of budget


def test_apply_budget_zero_budget():
    priced = [_card("Sol Ring", Decimal("2.00"), 1)]
    result = apply_budget(priced, Decimal("0.00"), "USD")

    assert result.lines[0].affordable_quantity == 0
    assert result.total_spent == Decimal("0.00")
    assert result.fully_covered is False
