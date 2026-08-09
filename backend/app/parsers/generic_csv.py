"""Generic CSV collection import — see IMPORT_FORMATS.md "Generic CSV".

Any CSV with at least a detectable/mapped card-name column and quantity
column. Columns are auto-detected the same tolerant way as ManaBox CSV; the
caller (import preview API) can pass an explicit `column_mapping` (canonical
field -> source header) to override auto-detection instead, e.g. after the
user corrects it in the UI. Unmapped columns are ignored.
"""
from __future__ import annotations

import csv
import io

from app.parsers.common import ParseResult, RowValidationError, detect_columns, map_collection_row

GENERIC_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "card name", "card"),
    "set_name": ("set name", "edition", "set"),
    "set_code": ("set code", "edition code", "set abbreviation"),
    "collector_number": ("collector number", "collector #", "card number", "number", "#"),
    "quantity": ("quantity", "qty", "count", "amount"),
    "foil": ("foil", "printing", "finish"),
    "language": ("language", "lang"),
    "condition": ("condition", "cond"),
    "purchase_price": ("purchase price", "price", "cost"),
    "purchase_currency": ("purchase currency", "currency"),
    "scryfall_id": ("scryfall id", "scryfallid", "scryfall_id"),
}


def parse_generic_csv(content: str, column_mapping: dict[str, str] | None = None) -> ParseResult:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise RowValidationError("file is empty")
    headers = list(reader.fieldnames)

    if column_mapping:
        unknown = set(column_mapping.values()) - set(headers)
        if unknown:
            raise RowValidationError(
                f"column mapping refers to header(s) not present in the file: {', '.join(sorted(unknown))}"
            )
        detected = dict(column_mapping)
    else:
        detected = detect_columns(headers, GENERIC_HEADER_ALIASES)

    if "name" not in detected:
        raise RowValidationError("no card-name column detected — map one explicitly via column_mapping")
    if "quantity" not in detected:
        raise RowValidationError("no quantity column detected — map one explicitly via column_mapping")

    result = ParseResult(detected_columns=detected)
    for row_number, raw in enumerate(reader, start=1):
        result.rows.append(map_collection_row(row_number, raw, detected))
    return result
