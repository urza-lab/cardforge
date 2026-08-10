"""Popular-deck discovery: sync orchestration (mirrors
app/services/mtgjson_service.py exactly) plus the read-side query the
browse API uses. See app/source_adapters/moxfield.py for the actual sync
work and app/models/discover.py for why this is a cache, not a live query.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.queue import get_queue
from app.models.discover import (
    DISCOVERY_SYNC_STATE_ID,
    DeckDiscoverySyncState,
    DeckDiscoverySyncStatus,
    PopularDeck,
)


class SyncAlreadyInProgressError(Exception):
    pass


def get_sync_state(db: Session) -> DeckDiscoverySyncState:
    state = db.get(DeckDiscoverySyncState, DISCOVERY_SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("deck_discovery_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> DeckDiscoverySyncState:
    state = get_sync_state(db)
    if state.status == DeckDiscoverySyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - avoids a hard import-time
    # dependency from the API process on the worker's job module (see
    # scryfall_service.trigger_sync for the same pattern).
    from app.workers.jobs import sync_popular_decks

    get_queue("default").enqueue(sync_popular_decks, job_timeout=300)
    state.status = DeckDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def list_popular_decks(
    db: Session, *, sort: str = "views", color_identity: str | None = None
) -> list[PopularDeck]:
    """`color_identity`, when given, is a set of WUBRG letters (e.g. "WU")
    - only decks whose own color identity is a subset of it are returned
    (so "WU" also surfaces a mono-W or mono-U deck, not just exact WU),
    matching how deckbuilding actually works ("what can I build in these
    colors") rather than an exact-match filter almost nothing would pass.
    """
    order_column = PopularDeck.like_count if sort == "likes" else PopularDeck.view_count
    stmt = select(PopularDeck).order_by(order_column.desc())
    decks = list(db.scalars(stmt))

    if color_identity:
        allowed = set(color_identity.upper())
        decks = [d for d in decks if set(d.color_identity or []) <= allowed]

    return decks
