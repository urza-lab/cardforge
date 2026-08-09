"""Text list collection import — see IMPORT_FORMATS.md "Text lists".

One card per line: `<quantity> <name>` or `<quantity> <name> (<set>) <collector
number>`. Blank lines and `#`-comments are skipped. The deck-only section
headers (`Commander:`, `Sideboard:`, ...) from IMPORT_FORMATS.md are Phase 5
(deck import) syntax, not valid in a *collection* text list — a line using
one is reported as a row error rather than silently misparsed as a card
named "Commander:".
"""
from __future__ import annotations

import re

from app.parsers.common import ParsedRow, ParseResult, RowValidationError, parse_quantity

_QTY_LINE_RE = re.compile(r"^(?P<quantity>\d+)x?\s+(?P<rest>.+)$")
_SET_SUFFIX_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<set_code>[A-Za-z0-9]{2,6})\)\s+(?P<collector_number>[A-Za-z0-9-]+)$"
)
_SECTION_HEADER_RE = re.compile(r"^(Commander|Companion|Sideboard|Maybeboard|Considering):", re.IGNORECASE)


def parse_text_list(content: str) -> ParseResult:
    result = ParseResult(detected_columns={"format": "text-list"})
    row_number = 0

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        row_number += 1
        raw = {"line": stripped}

        if _SECTION_HEADER_RE.match(stripped):
            result.rows.append(
                ParsedRow(
                    row_number=row_number,
                    raw=raw,
                    error="deck section headers (Commander:/Sideboard:/...) are not valid in a collection import",
                )
            )
            continue

        match = _QTY_LINE_RE.match(stripped)
        if not match:
            result.rows.append(
                ParsedRow(
                    row_number=row_number,
                    raw=raw,
                    error=f"line does not match '<quantity> <card name>': '{stripped}'",
                )
            )
            continue

        try:
            quantity = parse_quantity(match.group("quantity"))
        except RowValidationError as exc:
            result.rows.append(ParsedRow(row_number=row_number, raw=raw, error=str(exc)))
            continue

        rest = match.group("rest").strip()
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
            "condition": None,
            "purchase_price": None,
            "purchase_currency": None,
            "scryfall_id": None,
        }
        result.rows.append(ParsedRow(row_number=row_number, raw=raw, mapped=mapped))

    return result
