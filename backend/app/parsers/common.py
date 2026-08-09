"""Shared types and row-mapping helpers for collection import parsers.

Parsers are pure functions: given raw text (and, for generic CSV, an
optional explicit column mapping), they return a ParseResult with no I/O, no
DB access, and no FastAPI imports (see ARCHITECTURE.md "Backend module
boundaries" — `parsers/` must stay pure functions like `comparison/`).
Persisting the result (as Import/ImportRow rows) is the import service's job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# Canonical fields every parser maps its source columns/tokens onto. These
# match CollectionItem's columns 1:1 (see app/models/collection.py) so the
# import service can build a CollectionItem straight from `mapped`.
CANONICAL_FIELDS = (
    "name",
    "set_code",
    "set_name",
    "collector_number",
    "quantity",
    "foil",
    "language",
    "condition",
    "purchase_price",
    "purchase_currency",
    "scryfall_id",
)

VALID_CONDITIONS = {"NM", "LP", "MP", "HP", "DMG"}


class RowValidationError(ValueError):
    """Raised for a problem confined to one row/entry (caught per-row) or,
    if raised out of a parser's top-level function, a file-level problem
    (missing required column, unparseable JSON) that aborts the whole parse.
    """


@dataclass
class ParsedRow:
    row_number: int  # 1-based, counted over data rows only (header excluded)
    raw: dict[str, Any]
    mapped: dict[str, Any] | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        return "error" if self.error else "ok"


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    # canonical field name -> source header/label that was used for it.
    detected_columns: dict[str, str] = field(default_factory=dict)

    @property
    def valid_rows(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.error is None]

    @property
    def error_rows(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.error is not None]


def normalize_header(header: str) -> str:
    return " ".join(header.strip().lower().replace("_", " ").replace("-", " ").split())


def detect_columns(headers: list[str], alias_map: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Map canonical field -> source header, case-insensitively tolerant of
    the variants listed in `alias_map`. First matching header wins.
    """
    normalized = [(header, normalize_header(header)) for header in headers]
    detected: dict[str, str] = {}
    for canonical_field, aliases in alias_map.items():
        for header, norm in normalized:
            if norm in aliases:
                detected[canonical_field] = header
                break
    return detected


def parse_quantity(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise RowValidationError("quantity is required")
    try:
        value = int(text)
    except ValueError as exc:
        raise RowValidationError(f"quantity '{raw}' is not a whole number") from exc
    if value <= 0:
        raise RowValidationError(f"quantity must be positive, got {value}")
    return value


def parse_foil(raw: str | bool | None) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return raw.strip().lower() in {"foil", "true", "yes", "y", "1"}


# Condition values as actually seen in the wild, not just IMPORT_FORMATS.md's
# short codes: ManaBox's own CSV export writes full words like "near_mint" /
# "lightly_played", and other tools/marketplaces use their own spellings for
# the same five conditions. All normalize to the canonical NM/LP/MP/HP/DMG
# code CollectionItem.condition actually stores.
_CONDITION_ALIASES: dict[str, str] = {
    "nm": "NM",
    "mint": "NM",
    "near mint": "NM",
    "m": "NM",
    "lp": "LP",
    "light played": "LP",
    "lightly played": "LP",
    "slightly played": "LP",
    "excellent": "LP",
    "sp": "LP",
    "mp": "MP",
    "moderate played": "MP",
    "moderately played": "MP",
    "played": "MP",
    "good": "MP",
    "hp": "HP",
    "heavy played": "HP",
    "heavily played": "HP",
    "dmg": "DMG",
    "damaged": "DMG",
    "poor": "DMG",
}


def parse_condition(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    normalized = normalize_header(raw)  # lowercase, underscores/hyphens -> spaces, collapsed
    condition = _CONDITION_ALIASES.get(normalized)
    if condition is None:
        raise RowValidationError(f"condition '{raw}' is not one of {', '.join(sorted(VALID_CONDITIONS))}")
    return condition


def parse_price(raw: str | None) -> Decimal | None:
    if raw is None or not raw.strip():
        return None
    text = raw.strip().replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise RowValidationError(f"purchase price '{raw}' is not a number") from exc


def parse_scryfall_id(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    # Loose UUID shape check only (not the stricter `uuid` module parse) —
    # exact printing resolution against it is Phase 3's job, not this one's.
    if len(value) != 36 or value.count("-") != 4:
        raise RowValidationError(f"scryfall id '{raw}' does not look like a UUID")
    return value


def map_collection_row(row_number: int, raw: dict[str, Any], detected: dict[str, str]) -> ParsedRow:
    """Shared row mapper for the two header/column-based formats (ManaBox and
    generic CSV): pulls each canonical field out of `raw` via `detected`,
    validates it, and returns one ParsedRow — ok or error, never partial.
    """

    def get(canonical_field: str) -> str | None:
        header = detected.get(canonical_field)
        if header is None:
            return None
        value = raw.get(header)
        return value if isinstance(value, str) else None

    clean_raw = {k: v for k, v in raw.items() if isinstance(k, str)}

    try:
        name = (get("name") or "").strip()
        if not name:
            raise RowValidationError("card name is required")
        price = parse_price(get("purchase_price"))
        mapped: dict[str, Any] = {
            "name": name,
            "set_name": (get("set_name") or "").strip() or None,
            "set_code": (get("set_code") or "").strip().upper() or None,
            "collector_number": (get("collector_number") or "").strip() or None,
            "quantity": parse_quantity(get("quantity") or ""),
            "foil": parse_foil(get("foil")),
            "language": (get("language") or "").strip().upper() or None,
            "condition": parse_condition(get("condition")),
            "purchase_price": str(price) if price is not None else None,
            "purchase_currency": (get("purchase_currency") or "").strip().upper() or None,
            "scryfall_id": parse_scryfall_id(get("scryfall_id")),
        }
    except RowValidationError as exc:
        return ParsedRow(row_number=row_number, raw=clean_raw, error=str(exc))

    return ParsedRow(row_number=row_number, raw=clean_raw, mapped=mapped)
