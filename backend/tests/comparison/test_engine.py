from __future__ import annotations

from app.comparison import ComparisonSettings, OwnedCard, RequiredCard, compare


def test_fully_buildable_oracle_mode():
    owned = [OwnedCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]
    required = [RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is True
    assert result.missing == []
    assert result.coverage_percent == 100.0


def test_missing_card_quantities():
    owned = [OwnedCard(name="Lightning Bolt", quantity=2, oracle_id="bolt")]
    required = [RequiredCard(name="Lightning Bolt", quantity=4, oracle_id="bolt")]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is False
    assert len(result.missing) == 1
    missing = result.missing[0]
    assert missing.required_quantity == 4
    assert missing.owned_quantity == 2
    assert missing.missing_quantity == 2


def test_coverage_percent_across_multiple_cards():
    owned = [
        OwnedCard(name="A", quantity=1, oracle_id="a"),
        OwnedCard(name="B", quantity=0, oracle_id="b"),
    ]
    required = [
        RequiredCard(name="A", quantity=1, oracle_id="a"),
        RequiredCard(name="B", quantity=1, oracle_id="b"),
    ]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.total_required_quantity == 2
    assert result.total_owned_quantity == 1
    assert result.coverage_percent == 50.0
    assert result.is_fully_buildable is False


def test_oracle_mode_sums_across_multiple_printings():
    owned = [
        OwnedCard(name="Lightning Bolt", quantity=2, oracle_id="bolt", scryfall_card_id="print-a"),
        OwnedCard(name="Lightning Bolt", quantity=2, oracle_id="bolt", scryfall_card_id="print-b"),
    ]
    required = [RequiredCard(name="Lightning Bolt", quantity=4, oracle_id="bolt")]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is True


def test_oracle_mode_falls_back_to_name_when_unresolved():
    # No Scryfall sync has run yet (or the card didn't resolve) - oracle_id
    # is None on both sides, matching must still work via normalized name.
    owned = [OwnedCard(name="  Sol Ring ", quantity=1)]
    required = [RequiredCard(name="sol ring", quantity=1)]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is True


def test_oracle_mode_different_names_do_not_match():
    owned = [OwnedCard(name="Sol Ring", quantity=1)]
    required = [RequiredCard(name="Mana Vault", quantity=1)]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is False
    assert result.missing[0].owned_quantity == 0


def test_printing_mode_matches_exact_printing_only():
    owned = [
        OwnedCard(name="Lightning Bolt", quantity=1, oracle_id="bolt", scryfall_card_id="print-a"),
        OwnedCard(name="Lightning Bolt", quantity=5, oracle_id="bolt", scryfall_card_id="print-b"),
    ]
    required = [RequiredCard(name="Lightning Bolt", quantity=1, oracle_id="bolt", scryfall_card_id="print-a")]

    result = compare(owned, required, ComparisonSettings(mode="printing"))

    assert result.is_fully_buildable is True
    # The 5 copies of print-b must not count toward a print-a requirement.
    assert result.total_owned_quantity == 1


def test_printing_mode_unresolved_owned_card_never_counts():
    owned = [OwnedCard(name="Lightning Bolt", quantity=10, oracle_id="bolt", scryfall_card_id=None)]
    required = [RequiredCard(name="Lightning Bolt", quantity=1, oracle_id="bolt", scryfall_card_id="print-a")]

    result = compare(owned, required, ComparisonSettings(mode="printing"))

    assert result.is_fully_buildable is False
    assert result.missing[0].owned_quantity == 0


def test_printing_mode_unresolved_required_card_is_always_missing():
    owned = [OwnedCard(name="Lightning Bolt", quantity=10, oracle_id="bolt", scryfall_card_id="print-a")]
    required = [RequiredCard(name="Lightning Bolt", quantity=1, oracle_id="bolt", scryfall_card_id=None)]

    result = compare(owned, required, ComparisonSettings(mode="printing"))

    assert result.is_fully_buildable is False
    assert result.missing[0].missing_quantity == 1


def test_duplicate_required_entries_share_the_same_owned_pool():
    owned = [OwnedCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]
    required = [
        RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring"),
        RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring"),
    ]

    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    # Only one copy owned - the second requirement line must not double-count it.
    assert result.total_owned_quantity == 1
    assert result.is_fully_buildable is False
    assert sum(m.missing_quantity for m in result.missing) == 1


def test_empty_required_list_is_fully_buildable():
    result = compare([OwnedCard(name="Sol Ring", quantity=1)], [], ComparisonSettings(mode="oracle"))

    assert result.is_fully_buildable is True
    assert result.coverage_percent == 100.0
    assert result.total_required_cards == 0


def test_default_mode_is_oracle():
    owned = [OwnedCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]
    required = [RequiredCard(name="Sol Ring", quantity=1, oracle_id="sol-ring")]

    result = compare(owned, required)

    assert result.mode == "oracle"
    assert result.is_fully_buildable is True
