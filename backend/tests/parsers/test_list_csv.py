from __future__ import annotations

import pytest
from app.parsers.common import RowValidationError
from app.parsers.list_csv import parse_list_csv


def test_auto_detects_headers_and_maps_section_category_tags():
    content = (
        "Name,Qty,Set Code,Section,Category,Tags\n"
        "Lightning Bolt,4,LEA,,Removal,\"burn,cheap\"\n"
        "\"Atraxa, Praetors' Voice\",1,ZNC,commander,,\n"
    )
    result = parse_list_csv(content)
    assert result.detected_columns["name"] == "Name"
    assert result.detected_columns["quantity"] == "Qty"
    assert result.error_rows == []
    assert len(result.valid_rows) == 2

    bolt = next(r for r in result.valid_rows if r.mapped["name"] == "Lightning Bolt")
    assert bolt.mapped["quantity"] == 4
    assert bolt.mapped["set_code"] == "LEA"
    assert bolt.mapped["section"] == "mainboard"
    assert bolt.mapped["category"] == "Removal"
    assert bolt.mapped["tags"] == ["burn", "cheap"]

    commander = next(r for r in result.valid_rows if "Atraxa" in r.mapped["name"])
    assert commander.mapped["section"] == "commander"
    assert commander.mapped["tags"] is None


def test_missing_name_and_quantity_columns_raises():
    with pytest.raises(RowValidationError):
        parse_list_csv("Foo,Bar\n1,2\n")


def test_invalid_section_is_a_row_error():
    content = "Name,Qty,Section\nSol Ring,1,not-a-real-section\n"
    result = parse_list_csv(content)
    assert result.error_rows
    assert "section" in result.error_rows[0].error.lower()


def test_explicit_column_mapping_overrides_autodetect():
    content = "MyCard,MyQty\nBlack Lotus,1\n"
    result = parse_list_csv(content, column_mapping={"name": "MyCard", "quantity": "MyQty"})
    assert result.rows[0].mapped["name"] == "Black Lotus"
    assert result.rows[0].mapped["quantity"] == 1


def test_explicit_column_mapping_with_unknown_header_raises():
    with pytest.raises(RowValidationError):
        parse_list_csv("A,B\n1,2\n", column_mapping={"name": "DoesNotExist", "quantity": "B"})
