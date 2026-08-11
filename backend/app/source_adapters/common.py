"""Shared types for public-URL deck adapters (moxfield.py, archidekt.py)."""
from __future__ import annotations

from dataclasses import dataclass

from app.parsers.common import ParseResult


@dataclass
class DeckFetchResult:
    deck_name: str | None
    parse_result: ParseResult


@dataclass(frozen=True)
class PopularDeckEntry:
    """One deck from a source's own popularity search — see
    app.services.discover_service.run_discovery_sync, which each adapter's
    own `fetch_popular_decks` feeds into.
    """

    external_id: str
    name: str
    author: str | None
    source_url: str
    format: str
    view_count: int
    like_count: int
    color_identity: list[str] | None
