from collections.abc import Callable

from app.parsers.common import ParseResult, RowValidationError
from app.parsers.generic_csv import parse_generic_csv
from app.parsers.json_list import parse_json_list
from app.parsers.list_text import parse_list_text
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

# Registry keyed by app.models.lists.ListImportSourceType values (Phase 4).
# generic_csv/manabox_csv are deliberately not offered here — see
# ARCHITECTURE.md: list import supports text/json only, for full
# section/category/tags fidelity.
LIST_PARSERS: dict[str, Callable[..., ParseResult]] = {
    "text": parse_list_text,
    "json": parse_json_list,
}

__all__ = [
    "LIST_PARSERS",
    "PARSERS",
    "ParseResult",
    "RowValidationError",
    "parse_generic_csv",
    "parse_json_list",
    "parse_list_text",
    "parse_manabox_csv",
    "parse_text_list",
]
