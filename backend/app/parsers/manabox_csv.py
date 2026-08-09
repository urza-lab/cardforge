"""ManaBox CSV collection export parser — see IMPORT_FORMATS.md "ManaBox CSV".

Column order is not assumed; columns are detected by header name via the
alias map below. If a Scryfall ID column is present it's carried through in
`mapped` (Phase 3 uses it to resolve the exact printing; Phase 2 just stores
it on the CollectionItem).
"""
from __future__ import annotations

import csv
import io

from app.parsers.common import ParseResult, RowValidationError, detect_columns, map_collection_row

MANABOX_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "card name"),
    "set_name": ("set name", "edition"),
    "set_code": ("set code", "edition code"),
    "collector_number": ("collector number", "collector #", "card number"),
    "quantity": ("quantity", "qty"),
    "foil": ("foil", "printing", "finish"),
    "language": ("language", "lang"),
    "condition": ("condition",),
    "purchase_price": ("purchase price", "price"),
    "purchase_currency": ("purchase currency", "currency"),
    "scryfall_id": ("scryfall id", "scryfallid"),
}


def parse_manabox_csv(content: str) -> ParseResult:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise RowValidationError("file is empty")

    detected = detect_columns(list(reader.fieldnames), MANABOX_HEADER_ALIASES)
    if "name" not in detected:
        raise RowValidationError("no 'Card name' column found in ManaBox CSV")
    if "quantity" not in detected:
        raise RowValidationError("no 'Quantity' column found in ManaBox CSV")

    result = ParseResult(detected_columns=detected)
    for row_number, raw in enumerate(reader, start=1):
        result.rows.append(map_collection_row(row_number, raw, detected))
    return result
