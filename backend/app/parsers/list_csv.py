"""CSV deck/cube import — see IMPORT_FORMATS.md "CSV" (list variant).

Not the same registry entry as collection import's generic_csv/manabox_csv
(app/parsers/generic_csv.py, manabox_csv.py) — those map onto CollectionItem
(condition/purchase price, no section/category/tags concept). This one
mirrors generic_csv's column-detection approach but maps onto CardListItem's
shape instead, via app.parsers.common.map_list_row.
"""
from __future__ import annotations

import csv
import io

from app.parsers.common import ParseResult, RowValidationError, detect_columns, map_list_row

LIST_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "card name", "card"),
    "set_name": ("set name", "edition", "set"),
    "set_code": ("set code", "edition code", "set abbreviation"),
    "collector_number": ("collector number", "collector #", "card number", "number", "#"),
    "quantity": ("quantity", "qty", "count", "amount"),
    "foil": ("foil", "printing", "finish"),
    "language": ("language", "lang"),
    "scryfall_id": ("scryfall id", "scryfallid", "scryfall_id"),
    "section": ("section", "board"),
    "category": ("category", "archetype", "role"),
    "tags": ("tags", "tag"),
}


def parse_list_csv(content: str, column_mapping: dict[str, str] | None = None) -> ParseResult:
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
        detected = detect_columns(headers, LIST_HEADER_ALIASES)

    if "name" not in detected:
        raise RowValidationError("no card-name column detected — map one explicitly via column_mapping")
    if "quantity" not in detected:
        raise RowValidationError("no quantity column detected — map one explicitly via column_mapping")

    result = ParseResult(detected_columns=detected)
    for row_number, raw in enumerate(reader, start=1):
        result.rows.append(map_list_row(row_number, raw, detected))
    return result
