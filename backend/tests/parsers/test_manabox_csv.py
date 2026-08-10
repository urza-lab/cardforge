from __future__ import annotations

import pytest
from app.parsers.common import RowValidationError
from app.parsers.manabox_csv import parse_manabox_csv

from tests.fixtures import EXAMPLES_DIR

FIXTURE = EXAMPLES_DIR / "manabox_collection.csv"


def test_parses_fixture_with_no_errors():
    result = parse_manabox_csv(FIXTURE.read_text())
    assert result.error_rows == []
    assert len(result.valid_rows) == 5


def test_maps_core_fields():
    result = parse_manabox_csv(FIXTURE.read_text())
    bolt = result.rows[0].mapped
    assert bolt["name"] == "Lightning Bolt"
    assert bolt["quantity"] == 4
    assert bolt["set_code"] == "LEA"
    assert bolt["scryfall_id"] == "e3285e6b-3e79-4d7c-bf96-d920f973b122"


def test_foil_detection():
    result = parse_manabox_csv(FIXTURE.read_text())
    sol_ring = next(r for r in result.rows if r.mapped and r.mapped["name"] == "Sol Ring")
    assert sol_ring.mapped["foil"] is True


def test_name_with_comma_is_handled_via_csv_quoting():
    result = parse_manabox_csv(FIXTURE.read_text())
    ragavan = next(r for r in result.rows if r.mapped and "Ragavan" in r.mapped["name"])
    assert ragavan.mapped["name"] == "Ragavan, Nimble Pilferer"


def test_column_order_independent():
    content = "Quantity,Name\n4,Lightning Bolt\n"
    result = parse_manabox_csv(content)
    assert result.rows[0].mapped["name"] == "Lightning Bolt"
    assert result.rows[0].mapped["quantity"] == 4


def test_missing_name_column_raises():
    with pytest.raises(RowValidationError):
        parse_manabox_csv("Set code,Quantity\nLEA,1\n")


def test_missing_quantity_column_raises():
    with pytest.raises(RowValidationError):
        parse_manabox_csv("Name\nLightning Bolt\n")


def test_bad_quantity_is_a_row_error_not_a_crash():
    result = parse_manabox_csv("Name,Quantity\nLightning Bolt,notanumber\n")
    assert len(result.rows) == 1
    assert result.rows[0].status == "error"
    assert "not a whole number" in result.rows[0].error


def test_zero_and_negative_quantity_are_rejected():
    result = parse_manabox_csv("Name,Quantity\nA,0\nB,-1\n")
    assert all(row.status == "error" for row in result.rows)


def test_invalid_condition_is_rejected():
    result = parse_manabox_csv("Name,Quantity,Condition\nLightning Bolt,1,PRISTINE\n")
    assert result.rows[0].status == "error"
    assert "condition" in result.rows[0].error


def test_manabox_long_form_conditions_are_normalized():
    # ManaBox's own CSV export writes full words with underscores, not the
    # NM/LP/MP/HP/DMG short codes from IMPORT_FORMATS.md.
    content = (
        "Name,Quantity,Condition\n"
        "A,1,near_mint\n"
        "B,1,lightly_played\n"
        "C,1,moderately_played\n"
        "D,1,heavily_played\n"
        "E,1,damaged\n"
    )
    result = parse_manabox_csv(content)
    assert result.error_rows == []
    assert [row.mapped["condition"] for row in result.rows] == ["NM", "LP", "MP", "HP", "DMG"]


def test_condition_matching_is_case_and_whitespace_insensitive():
    result = parse_manabox_csv("Name,Quantity,Condition\nA,1,Near Mint\nB,1, NM \n")
    assert [row.mapped["condition"] for row in result.rows] == ["NM", "NM"]


def test_invalid_scryfall_id_is_rejected():
    result = parse_manabox_csv("Name,Quantity,Scryfall ID\nLightning Bolt,1,not-a-uuid\n")
    assert result.rows[0].status == "error"


def test_empty_file_raises():
    with pytest.raises(RowValidationError):
        parse_manabox_csv("")
