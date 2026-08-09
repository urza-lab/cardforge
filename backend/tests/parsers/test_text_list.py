from __future__ import annotations

from app.parsers.text_list import parse_text_list
from tests.fixtures import EXAMPLES_DIR

FIXTURE = EXAMPLES_DIR / "collection_list.txt"


def test_parses_fixture_with_no_errors():
    result = parse_text_list(FIXTURE.read_text())
    assert result.error_rows == []
    assert len(result.valid_rows) == 5


def test_parses_set_and_collector_number_suffix():
    result = parse_text_list("1 Sol Ring (C21) 263\n")
    row = result.rows[0]
    assert row.mapped["name"] == "Sol Ring"
    assert row.mapped["set_code"] == "C21"
    assert row.mapped["collector_number"] == "263"


def test_plain_quantity_name_line():
    result = parse_text_list("4 Lightning Bolt\n")
    assert result.rows[0].mapped == {
        "name": "Lightning Bolt",
        "set_name": None,
        "set_code": None,
        "collector_number": None,
        "quantity": 4,
        "foil": False,
        "language": None,
        "condition": None,
        "purchase_price": None,
        "purchase_currency": None,
        "scryfall_id": None,
    }


def test_x_suffix_quantity():
    result = parse_text_list("3x Brainstorm\n")
    assert result.rows[0].mapped["quantity"] == 3
    assert result.rows[0].mapped["name"] == "Brainstorm"


def test_blank_lines_and_comments_are_skipped():
    result = parse_text_list("\n# a comment\n4 Lightning Bolt\n\n")
    assert len(result.rows) == 1


def test_section_header_is_a_row_error_in_collection_import():
    result = parse_text_list("Commander: Atraxa, Praetors' Voice\n")
    assert result.rows[0].status == "error"
    assert "section header" in result.rows[0].error


def test_unparseable_line_is_a_row_error():
    result = parse_text_list("not a valid line at all\n")
    assert result.rows[0].status == "error"


def test_zero_quantity_is_a_row_error():
    result = parse_text_list("0 Lightning Bolt\n")
    assert result.rows[0].status == "error"
