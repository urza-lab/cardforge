"""Shared types for public-URL deck adapters (moxfield.py, archidekt.py)."""
from __future__ import annotations

from dataclasses import dataclass

from app.parsers.common import ParseResult


@dataclass
class DeckFetchResult:
    deck_name: str | None
    parse_result: ParseResult
