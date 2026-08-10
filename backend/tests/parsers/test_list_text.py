from __future__ import annotations

from app.parsers.list_text import parse_list_text


def test_plain_mainboard_line():
    result = parse_list_text("4 Lightning Bolt\n")
    assert result.rows[0].mapped["name"] == "Lightning Bolt"
    assert result.rows[0].mapped["quantity"] == 4
    assert result.rows[0].mapped["section"] == "mainboard"


def test_commander_header_switches_section_for_following_lines():
    content = "4 Lightning Bolt\nCommander:\n1 Atraxa, Praetors' Voice\n"
    result = parse_list_text(content)
    assert result.rows[0].mapped["section"] == "mainboard"
    assert result.rows[1].mapped["section"] == "commander"
    assert result.rows[1].mapped["name"] == "Atraxa, Praetors' Voice"


def test_commander_card_inline_with_header():
    result = parse_list_text("Commander: Atraxa, Praetors' Voice\n")
    row = result.rows[0]
    assert row.mapped["section"] == "commander"
    assert row.mapped["name"] == "Atraxa, Praetors' Voice"
    assert row.mapped["quantity"] == 1  # no count prefix - defaults to 1


def test_bare_section_header_is_not_a_row():
    result = parse_list_text("Sideboard:\n1 Rest in Peace\n")
    assert len(result.rows) == 1
    assert result.rows[0].mapped["section"] == "sideboard"


def test_all_section_headers_recognized():
    content = (
        "1 A\n"
        "Commander:\n1 B\n"
        "Companion:\n1 C\n"
        "Sideboard:\n1 D\n"
        "Maybeboard:\n1 E\n"
        "Considering:\n1 F\n"
    )
    result = parse_list_text(content)
    sections = [row.mapped["section"] for row in result.rows]
    assert sections == ["mainboard", "commander", "companion", "sideboard", "maybeboard", "considering"]


def test_set_and_collector_number_suffix_still_works():
    result = parse_list_text("1 Sol Ring (C21) 263\n")
    row = result.rows[0]
    assert row.mapped["set_code"] == "C21"
    assert row.mapped["collector_number"] == "263"


def test_section_persists_until_next_header():
    content = "Sideboard:\n1 A\n1 B\n"
    result = parse_list_text(content)
    assert [r.mapped["section"] for r in result.rows] == ["sideboard", "sideboard"]


def test_blank_lines_and_comments_skipped():
    result = parse_list_text("\n# comment\n4 Lightning Bolt\n\n")
    assert len(result.rows) == 1


def test_zero_quantity_is_a_row_error():
    result = parse_list_text("0 Lightning Bolt\n")
    assert result.rows[0].status == "error"
