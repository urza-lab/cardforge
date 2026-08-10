"""JSON collection/list import — see IMPORT_FORMATS.md "JSON".

Accepts `{"name": ..., "cards": [...]}` or a bare `[...]` array of card
objects. Shared by collection import (Phase 2) and list/deck/cube import
(Phase 4): `section`/`category`/`tags` are parsed into `mapped` for list
import to use; collection import (app/services/import_service.py) simply
never reads those three keys.
"""
from __future__ import annotations

import json
from typing import Any

from app.parsers.common import (
    ParsedRow,
    ParseResult,
    RowValidationError,
    parse_condition,
    parse_foil,
    parse_price,
    parse_quantity,
    parse_scryfall_id,
    parse_section,
)


def parse_json_list(content: str) -> ParseResult:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RowValidationError(f"invalid JSON: {exc}") from exc

    cards_field: Any
    if isinstance(data, list):
        cards_field = data
    elif isinstance(data, dict):
        cards_field = data.get("cards")
    else:
        raise RowValidationError("JSON must be an object with a 'cards' array, or a bare array of cards")

    if not isinstance(cards_field, list):
        raise RowValidationError("JSON object must have a 'cards' array")
    cards: list[Any] = cards_field

    result = ParseResult(detected_columns={"format": "json"})
    for row_number, entry in enumerate(cards, start=1):
        result.rows.append(_parse_entry(row_number, entry))
    return result


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_tags(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        tags = [t.strip() for t in value.split(",") if t.strip()]
    elif isinstance(value, list):
        tags = [str(t).strip() for t in value if str(t).strip()]
    else:
        raise RowValidationError(f"tags must be a list of strings or a comma-separated string, got {value!r}")
    return tags or None


def _parse_entry(row_number: int, entry: Any) -> ParsedRow:
    if not isinstance(entry, dict):
        return ParsedRow(row_number=row_number, raw={"value": entry}, error="card entry must be a JSON object")

    raw: dict[str, Any] = dict(entry)

    try:
        name = _as_str(entry.get("name"))
        if not name:
            raise RowValidationError("card name is required")
        if "quantity" not in entry or entry.get("quantity") is None:
            raise RowValidationError("quantity is required")
        quantity = parse_quantity(str(entry["quantity"]))
        price = parse_price(_as_str(entry.get("purchase_price")))
        set_code = _as_str(entry.get("set") or entry.get("set_code"))
        mapped: dict[str, Any] = {
            "name": name,
            "set_name": _as_str(entry.get("set_name")),
            "set_code": set_code.upper() if set_code else None,
            "collector_number": _as_str(entry.get("collector_number")),
            "quantity": quantity,
            "foil": parse_foil(entry.get("foil")),
            "language": (_as_str(entry.get("language")) or "").upper() or None,
            "condition": parse_condition(_as_str(entry.get("condition"))),
            "purchase_price": str(price) if price is not None else None,
            "purchase_currency": (_as_str(entry.get("purchase_currency")) or "").upper() or None,
            "scryfall_id": parse_scryfall_id(_as_str(entry.get("scryfall_id"))),
            "section": parse_section(_as_str(entry.get("section"))),
            "category": _as_str(entry.get("category")),
            "tags": _as_tags(entry.get("tags")),
        }
    except RowValidationError as exc:
        return ParsedRow(row_number=row_number, raw=raw, error=str(exc))

    return ParsedRow(row_number=row_number, raw=raw, mapped=mapped)
