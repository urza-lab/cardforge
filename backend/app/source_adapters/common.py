"""Shared types for public-URL deck adapters (moxfield.py, archidekt.py)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    # WotC's official Commander Bracket (1-5), where the source exposes one -
    # confirmed live only on Archidekt (`edhBracket`); Moxfield's search API
    # has no equivalent field at all. None means "not set by the deck's own
    # author," not "unknown" - most decks on either source don't have one.
    bracket: int | None = None
    # Real, free fields from each source's own search response (verified
    # live - see CLAUDE.md) - user-requested after deck *names* alone turned
    # out too unreliable/unsystematic for real browsing/filtering.
    has_primer: bool = False
    deck_size: int | None = None
    theorycrafted: bool | None = None  # Archidekt only - see app.models.discover.PopularDeck
    comment_count: int = 0
    bookmark_count: int | None = None  # Moxfield only
    deck_updated_at: datetime | None = None
    tags: list[str] | None = None
    # Moxfield-internal id for the deck's "main card" (its commander, for a
    # Commander-format deck) - transient, not stored on PopularDeck itself.
    # discover_service resolves this to a real commander name via
    # moxfield.resolve_commander_names *after* fetch_popular_decks returns
    # (that function stays a pure, DB-free fetch - see its own docstring),
    # then fills PopularDeckEntry.commander_name in with dataclasses.replace.
    # Always None for Archidekt entries (no equivalent field exists there).
    main_card_id: str | None = None
    commander_name: str | None = None
