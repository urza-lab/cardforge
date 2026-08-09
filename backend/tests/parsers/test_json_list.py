from __future__ import annotations

import pytest

from app.parsers.common import RowValidationError
from app.parsers.json_list import parse_json_list
from tests.fixtures import EXAMPLES_DIR

FIXTURE = EXAMPLES_DIR / "collection.json"


def test_parses_fixture_with_no_errors():
    result = parse_json_list(FIXTURE.read_text())
    assert result.error_rows == []
    assert len(result.valid_rows) == 3
    assert result.rows[1].mapped["foil"] is True


def test_bare_array_is_accepted():
    result = parse_json_list('[{"name": "Sol Ring", "quantity": 1}]')
    assert result.rows[0].mapped["name"] == "Sol Ring"


def test_invalid_json_raises():
    with pytest.raises(RowValidationError):
        parse_json_list("{not json")


def test_missing_cards_array_raises():
    with pytest.raises(RowValidationError):
        parse_json_list('{"name": "no cards field"}')


def test_entry_missing_quantity_is_row_error():
    result = parse_json_list('{"cards": [{"name": "Sol Ring"}]}')
    assert result.rows[0].status == "error"
    assert "quantity" in result.rows[0].error


def test_entry_that_is_not_an_object_is_row_error():
    result = parse_json_list('{"cards": ["Sol Ring"]}')
    assert result.rows[0].status == "error"


def test_set_field_maps_to_set_code():
    result = parse_json_list('{"cards": [{"name": "Sol Ring", "quantity": 1, "set": "c21"}]}')
    assert result.rows[0].mapped["set_code"] == "C21"
