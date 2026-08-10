"""Plain CSV exports — generic CSV back out (see IMPORT_FORMATS.md "Generic
CSV"), so a round trip through another tool (or back into CardForge) doesn't
lose data. No library beyond the stdlib `csv` module; these are small files.
"""
from __future__ import annotations

import csv
import io

from app.models.collection import CollectionItem
from app.models.lists import CardListItem


def collection_items_to_csv(items: list[CollectionItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Name",
            "Set code",
            "Set name",
            "Collector number",
            "Quantity",
            "Foil",
            "Language",
            "Condition",
            "Purchase price",
            "Purchase currency",
            "Scryfall ID",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item.card_name,
                item.set_code or "",
                item.set_name or "",
                item.collector_number or "",
                item.quantity,
                "foil" if item.foil else "normal",
                item.language or "",
                item.condition or "",
                item.purchase_price if item.purchase_price is not None else "",
                item.purchase_currency or "",
                item.scryfall_id or "",
            ]
        )
    return buffer.getvalue()


def list_items_to_csv(items: list[CardListItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Name", "Section", "Quantity", "Set code", "Set name", "Collector number", "Category", "Tags", "Foil"]
    )
    for item in items:
        writer.writerow(
            [
                item.card_name,
                item.section,
                item.quantity,
                item.set_code or "",
                item.set_name or "",
                item.collector_number or "",
                item.category or "",
                ",".join(item.tags) if item.tags else "",
                "foil" if item.foil else "normal",
            ]
        )
    return buffer.getvalue()
