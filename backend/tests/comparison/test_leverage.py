from __future__ import annotations

from app.comparison import ComparisonSettings, OwnedCard, RequiredCard
from app.comparison.leverage import compute_leverage


def test_card_that_completes_two_decks_ranks_first():
    owned: list[OwnedCard] = []
    lists_required = {
        "deck-a": [RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")],
        "deck-b": [RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")],
        "deck-c": [
            RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring"),
            RequiredCard(name="Lightning Bolt", quantity=1, oracle_id="bolt"),
        ],
    }

    candidates = compute_leverage(owned, lists_required, ComparisonSettings(mode="oracle"))

    sol_ring = next(c for c in candidates if c.oracle_id == "sol-ring")
    # All three decks want 1 Sol Ring each - 3 copies needed to cover every
    # shortfall. Only deck-a and deck-b become fully buildable from that
    # alone though - deck-c also needs Bolt, so it stays incomplete.
    assert sol_ring.quantity_needed == 3
    assert sol_ring.lists_newly_buildable == 2
    # Highest lists_newly_buildable sorts first.
    assert candidates[0].oracle_id == "sol-ring"


def test_card_that_only_partially_helps_has_zero_newly_buildable_but_positive_gain():
    owned: list[OwnedCard] = []
    lists_required = {
        "deck-a": [
            RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring"),
            RequiredCard(name="Lightning Bolt", quantity=1, oracle_id="bolt"),
        ],
    }

    candidates = compute_leverage(owned, lists_required, ComparisonSettings(mode="oracle"))

    sol_ring = next(c for c in candidates if c.oracle_id == "sol-ring")
    assert sol_ring.lists_newly_buildable == 0
    assert sol_ring.total_coverage_gain > 0


def test_already_owned_card_is_not_a_candidate():
    owned = [OwnedCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]
    lists_required = {"deck-a": [RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]}

    candidates = compute_leverage(owned, lists_required, ComparisonSettings(mode="oracle"))
    assert candidates == []


def test_empty_lists_required_returns_empty():
    assert compute_leverage([], {}, ComparisonSettings(mode="oracle")) == []


def test_printing_mode_uses_scryfall_card_id():
    owned: list[OwnedCard] = []
    lists_required = {
        "deck-a": [RequiredCard(name="Sol Ring", quantity=1, scryfall_card_id="printing-1")],
        "deck-b": [RequiredCard(name="Sol Ring", quantity=1, scryfall_card_id="printing-1")],
    }

    candidates = compute_leverage(owned, lists_required, ComparisonSettings(mode="printing"))

    assert len(candidates) == 1
    assert candidates[0].scryfall_card_id == "printing-1"
    assert candidates[0].lists_newly_buildable == 2
