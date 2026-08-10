from __future__ import annotations

import pytest
from app.parsers.common import RowValidationError
from app.parsers.generic_csv import parse_generic_csv

from tests.fixtures import EXAMPLES_DIR

FIXTURE = EXAMPLES_DIR / "generic_collection.csv"


def test_auto_detects_unconventional_headers():
    result = parse_generic_csv(FIXTURE.read_text())
    assert result.detected_columns["name"] == "Card"
    assert result.detected_columns["quantity"] == "Qty"
    assert result.detected_columns["collector_number"] == "Number"
    assert result.error_rows == []
    assert len(result.valid_rows) == 3


def test_unmapped_column_is_ignored_not_erroring():
    result = parse_generic_csv(FIXTURE.read_text())
    assert "Notes" not in result.detected_columns.values()
    goyf = next(r for r in result.rows if r.mapped and r.mapped["name"] == "Tarmogoyf")
    assert goyf.mapped["foil"] is True
    assert "Notes" not in goyf.mapped


def test_missing_name_and_quantity_columns_raises():
    with pytest.raises(RowValidationError):
        parse_generic_csv("Foo,Bar\n1,2\n")


def test_explicit_column_mapping_overrides_autodetect():
    content = "MyCard,MyQty\nBlack Lotus,1\n"
    result = parse_generic_csv(content, column_mapping={"name": "MyCard", "quantity": "MyQty"})
    assert result.rows[0].mapped["name"] == "Black Lotus"
    assert result.rows[0].mapped["quantity"] == 1


def test_explicit_column_mapping_with_unknown_header_raises():
    with pytest.raises(RowValidationError):
        parse_generic_csv("A,B\n1,2\n", column_mapping={"name": "DoesNotExist", "quantity": "B"})
