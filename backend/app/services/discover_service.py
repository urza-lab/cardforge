"""Popular-deck discovery: sync orchestration (mirrors
app/services/mtgjson_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/moxfield.py and
archidekt.py for each source's own `fetch_popular_decks`, and
app/models/discover.py for why this is a cache, not a live query.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.comparison import ComparisonSettings, RequiredCard, compare
from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.discover import (
    DISCOVERY_SYNC_STATE_ID,
    DeckDiscoverySyncState,
    DeckDiscoverySyncStatus,
    PopularDeck,
)
from app.services import pricing_service, scryfall_resolution
from app.services.comparison_service import _owned_cards
from app.source_adapters import archidekt, moxfield
from app.source_adapters.common import PopularDeckEntry

# One entry per discovery source - each source only ever touches its own
# rows (delete-then-reinsert scoped by `source`), so adding a third source
# later is just adding another tuple here.
_SOURCES: list[tuple[str, Callable[[str], list[PopularDeckEntry]]]] = [
    ("moxfield", moxfield.fetch_popular_decks),
    ("archidekt", archidekt.fetch_popular_decks),
]

# Same two sources, keyed for price_popular_deck's real per-deck fetch
# (fetch_and_parse) - the URL-import pipeline's own adapters
# (app.services.list_import_service.URL_ADAPTERS), reused rather than
# duplicated since a PopularDeck.source_url is exactly the same kind of URL
# an import would fetch.
_URL_ADAPTER_BY_SOURCE = {"moxfield": moxfield, "archidekt": archidekt}


class SyncAlreadyInProgressError(Exception):
    pass


class DeckNotFoundError(Exception):
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

    # 1800s: the original 900s estimate (Moxfield ~150s + Archidekt ~100s,
    # from each adapter's per-request pacing constant times its page count)
    # turned out wrong live - a real sync at the current pool sizes
    # (Moxfield 50 pages/sort, Archidekt 200 pages) hit the 900s ceiling and
    # got killed by RQ's JobTimeoutException with *nothing* committed (the
    # delete-then-reinsert per source only commits once that source's whole
    # fetch_popular_decks() call returns), even though isolated timing
    # samples of both APIs during the same investigation showed nowhere
    # near that per-request. Root cause wasn't nailed down (sustained-load
    # server-side slowdown neither adapter's short isolated probe would
    # trigger is the leading theory) - doubled the timeout to a value with
    # real headroom over what was actually observed, rather than re-guessing
    # a "should be enough" number a second time.
    get_queue("default").enqueue(sync_popular_decks, job_timeout=1800)
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
                        "bracket": d.bracket,
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
    db: Session,
    *,
    sort: str = "views",
    color_identity: str | None = None,
    source: str | None = None,
    bracket: int | None = None,
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
    `bracket`, when given, is an exact match against WotC's Commander
    Bracket (1-5) - only real for Archidekt-sourced decks that set one
    (~15% of them, confirmed live); Moxfield decks and most Archidekt decks
    have no bracket at all and are excluded when this filter is active,
    same "omit rather than fabricate" reasoning as everywhere else real
    data might just not exist for a given row.
    """
    order_column = PopularDeck.like_count if sort == "likes" else PopularDeck.view_count
    stmt = select(PopularDeck).order_by(order_column.desc())
    if source:
        stmt = stmt.where(PopularDeck.source == source)
    if bracket is not None:
        stmt = stmt.where(PopularDeck.bracket == bracket)
    decks = list(db.scalars(stmt))

    if color_identity:
        allowed = set(color_identity.upper())
        decks = [d for d in decks if set(d.color_identity or []) <= allowed]

    return decks


def price_popular_deck(
    db: Session, deck_id: int, *, collection_id: int, price_profile_id: int, user_agent: str
) -> PopularDeck:
    """Lazy pricing (user-requested): a `PopularDeck` row only ever caches
    search-result metadata (see app/models/discover.py), never a full card
    list - unlike app.services.precon_service, whose MTGJSON source already
    hands over every deck's complete list at sync time, computing a real
    price here means a real per-deck fetch to the original source, the same
    one `create_preview_from_url` makes at import time. Deliberately not run
    for every cached deck on every sync (that's ~1,000+ external requests to
    sites this project doesn't control - a real rate-limit risk, see
    ARCHITECTURE.md) - only for the one deck a caller actually asks to
    price, with the result cached on the row so a repeat view is free.
    """
    deck = db.get(PopularDeck, deck_id)
    if deck is None:
        raise DeckNotFoundError(deck_id)

    profile = pricing_service.get_price_profile(db, price_profile_id)
    if profile is None:
        raise pricing_service.PriceProfileNotFoundError(price_profile_id)

    adapter = _URL_ADAPTER_BY_SOURCE.get(deck.source)
    if adapter is None:
        raise ValueError(f"no URL adapter for discovery source '{deck.source}'")
    fetch_result = adapter.fetch_and_parse(deck.source_url, user_agent)

    required: list[RequiredCard] = []
    for row in fetch_result.parse_result.rows:
        if row.mapped is None:
            continue
        oracle_id, scryfall_card_id = scryfall_resolution.resolve_card(
            db,
            name=row.mapped["name"],
            set_code=row.mapped["set_code"],
            collector_number=row.mapped["collector_number"],
            language=row.mapped["language"],
            scryfall_id=row.mapped["scryfall_id"],
        )
        required.append(
            RequiredCard(
                name=row.mapped["name"],
                quantity=row.mapped["quantity"],
                oracle_id=oracle_id,
                scryfall_card_id=scryfall_card_id,
            )
        )

    owned = _owned_cards(db, collection_id)
    result = compare(owned, required, ComparisonSettings(mode="oracle"))

    priced = pricing_service.price_missing_cards(db, result.missing, profile, result.mode)
    priced_amounts = [p.unit_price * p.missing_quantity for p in priced if p.unit_price is not None]
    unpriced_count = sum(1 for p in priced if p.unit_price is None)

    deck.coverage_percent = result.coverage_percent
    deck.missing_cost = sum(priced_amounts, Decimal("0"))
    deck.missing_cost_currency = profile.currency
    deck.unpriced_missing_count = unpriced_count
    deck.priced_at = datetime.now(UTC)
    db.commit()
    db.refresh(deck)
    return deck
