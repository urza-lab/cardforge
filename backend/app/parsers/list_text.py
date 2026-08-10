"""Text list deck/cube import — see IMPORT_FORMATS.md "Text lists" for the
section syntax (`Commander:`, `Companion:`, `Sideboard:`, `Maybeboard:`,
`Considering:`). Lines before the first section header are "mainboard".
A quantity prefix is optional (defaults to 1) — IMPORT_FORMATS.md's own
example writes `Commander: Atraxa, Praetors' Voice` with no count.

Distinct from app/parsers/text_list.py (collection import), which rejects
these same section headers as row errors — a collection has no concept of
"sideboard", but a deck/cube list does.
"""
from __future__ import annotations

import re

from app.parsers.common import ParsedRow, ParseResult, RowValidationError, parse_quantity

_QTY_LINE_RE = re.compile(r"^(?P<quantity>\d+)x?\s+(?P<rest>.+)$")
_SET_SUFFIX_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<set_code>[A-Za-z0-9]{2,6})\)\s+(?P<collector_number>[A-Za-z0-9-]+)$"
)
_SECTION_HEADER_RE = re.compile(
    r"^(?P<section>Commander|Companion|Sideboard|Maybeboard|Considering):\s*(?P<rest>.*)$", re.IGNORECASE
)


def parse_list_text(content: str) -> ParseResult:
    result = ParseResult(detected_columns={"format": "text-list"})
    row_number = 0
    section = "mainboard"

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        header_match = _SECTION_HEADER_RE.match(stripped)
        if header_match:
            section = header_match.group("section").lower()
            remainder = header_match.group("rest").strip()
            if not remainder:
                continue  # a bare "Commander:" line just switches section - not a card entry
            stripped = remainder  # "Commander: Atraxa, Praetors' Voice" - card on the same line

        row_number += 1
        raw = {"line": stripped, "section": section}

        qty_match = _QTY_LINE_RE.match(stripped)
        quantity_str, rest = (qty_match.group("quantity"), qty_match.group("rest").strip()) if qty_match else (
            "1",
            stripped,
        )

        try:
            quantity = parse_quantity(quantity_str)
        except RowValidationError as exc:
            result.rows.append(ParsedRow(row_number=row_number, raw=raw, error=str(exc)))
            continue

        set_match = _SET_SUFFIX_RE.match(rest)
        if set_match:
            name = set_match.group("name").strip()
            set_code = set_match.group("set_code").upper()
            collector_number = set_match.group("collector_number")
        else:
            name = rest
            set_code = None
            collector_number = None

        if not name:
            result.rows.append(ParsedRow(row_number=row_number, raw=raw, error="card name is required"))
            continue

        mapped = {
            "name": name,
            "set_name": None,
            "set_code": set_code,
            "collector_number": collector_number,
            "quantity": quantity,
            "foil": False,
            "language": None,
            "scryfall_id": None,
            "section": section,
            "category": None,
            "tags": None,
        }
        result.rows.append(ParsedRow(row_number=row_number, raw=raw, mapped=mapped))

    return result
