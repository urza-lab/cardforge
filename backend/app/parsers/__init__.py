from collections.abc import Callable

from app.parsers.common import ParseResult, RowValidationError
from app.parsers.generic_csv import parse_generic_csv
from app.parsers.json_list import parse_json_list
from app.parsers.manabox_csv import parse_manabox_csv
from app.parsers.text_list import parse_text_list

# Registry keyed by app.models.imports.ImportSourceType values. Kept here
# (rather than making the service import each parser module directly) so
# adding a new format is adding one entry, not touching the service.
PARSERS: dict[str, Callable[..., ParseResult]] = {
    "manabox_csv": parse_manabox_csv,
    "generic_csv": parse_generic_csv,
    "text_list": parse_text_list,
    "json": parse_json_list,
}

__all__ = [
    "PARSERS",
    "ParseResult",
    "RowValidationError",
    "parse_generic_csv",
    "parse_json_list",
    "parse_manabox_csv",
    "parse_text_list",
]
