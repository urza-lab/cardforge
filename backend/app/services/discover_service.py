"""Popular-deck discovery: sync orchestration (mirrors
app/services/mtgjson_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/moxfield.py and
archidekt.py for each source's own `fetch_popular_decks`, and
app/models/discover.py for why this is a cache, not a live query.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.discover import (
    DISCOVERY_SYNC_STATE_ID,
    DeckDiscoverySyncState,
    DeckDiscoverySyncStatus,
    PopularDeck,
)
from app.source_adapters import archidekt, moxfield
from app.source_adapters.common import PopularDeckEntry

# One entry per discovery source - each source only ever touches its own
# rows (delete-then-reinsert scoped by `source`), so adding a third source
# later is just adding another tuple here.
_SOURCES: list[tuple[str, Callable[[str], list[PopularDeckEntry]]]] = [
    ("moxfield", moxfield.fetch_popular_decks),
    ("archidekt", archidekt.fetch_popular_decks),
]


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


def run_discovery_sync(db: Session, settings: Settings | None = None) -> DeckDiscoverySyncState:
    """Refreshes the popular_decks cache from every real source in
    `_SOURCES`, one source at a time. A single source failing (e.g. Moxfield
    rate-limiting again) doesn't lose the other source's decks or block them
    from refreshing - it's recorded in `error_message` and the sync still
    ends CURRENT if at least one source succeeded, matching "no fake
    success": a real partial failure stays visible, it's just not treated as
    a total outage when it isn't one. Only ends FAILED if every source
    failed (deck_count then reflects whatever was cached from a previous
    successful sync of a source that failed this time, since that source's
    rows are only deleted right before its own successful reinsert).
    """
    settings = settings or get_settings()
    state = get_sync_state(db)

    state.status = DeckDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    errors: list[str] = []
    for source_name, fetch_fn in _SOURCES:
        try:
            decks = fetch_fn(settings.scryfall_user_agent)
        except Exception as exc:  # noqa: BLE001 - one source's failure must not abort the others
            errors.append(f"{source_name}: {exc}")
            continue

        db.execute(delete(PopularDeck).where(PopularDeck.source == source_name))
        if decks:
            db.execute(
                insert(PopularDeck),
                [
                    {
                        "source": source_name,
                        "external_id": d.external_id,
                        "name": d.name,
                        "author": d.author,
                        "source_url": d.source_url,
                        "format": d.format,
                        "view_count": d.view_count,
                        "like_count": d.like_count,
                        "color_identity": d.color_identity,
                    }
                    for d in decks
                ],
            )
        db.commit()

    total = db.scalar(select(func.count()).select_from(PopularDeck))

    if errors and len(errors) == len(_SOURCES):
        state.status = DeckDiscoverySyncStatus.failed.value
        state.error_message = "; ".join(errors)[:1024]
    else:
        state.status = DeckDiscoverySyncStatus.current.value
        state.error_message = "; ".join(errors)[:1024] if errors else None
    state.deck_count = total or 0
    state.finished_at = datetime.now(UTC)
    db.commit()

    if errors and len(errors) == len(_SOURCES):
        raise RuntimeError(state.error_message)

    return state


def list_popular_decks(
    db: Session, *, sort: str = "views", color_identity: str | None = None, source: str | None = None
) -> list[PopularDeck]:
    """`color_identity`, when given, is a set of WUBRG letters (e.g. "WU")
    - only decks whose own color identity is a subset of it are returned
    (so "WU" also surfaces a mono-W or mono-U deck, not just exact WU),
    matching how deckbuilding actually works ("what can I build in these
    colors") rather than an exact-match filter almost nothing would pass.
    `source`, when given, restricts to one discovery source (e.g. "moxfield"
    or "archidekt") - omitted, all sources are mixed together sorted by the
    same column (archidekt decks always sort last under "likes" since that
    source has no reliable like signal - see archidekt.fetch_popular_decks).
    """
    order_column = PopularDeck.like_count if sort == "likes" else PopularDeck.view_count
    stmt = select(PopularDeck).order_by(order_column.desc())
    if source:
        stmt = stmt.where(PopularDeck.source == source)
    decks = list(db.scalars(stmt))

    if color_identity:
        allowed = set(color_identity.upper())
        decks = [d for d in decks if set(d.color_identity or []) <= allowed]

    return decks
