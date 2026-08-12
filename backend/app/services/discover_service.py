"""Popular-deck discovery: sync orchestration (mirrors
app/services/mtgjson_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/moxfield.py and
archidekt.py for each source's own `fetch_popular_decks`, and
app/models/discover.py for why this is a cache, not a live query.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
    MoxfieldCommanderCache,
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

    # 1800s -> 14400s (4h): the original 900s estimate (Moxfield ~150s +
    # Archidekt ~100s, from each adapter's per-request pacing constant times
    # its page count) turned out wrong live once - a real sync hit the 900s
    # ceiling and got killed by RQ's JobTimeoutException with *nothing*
    # committed, doubled to 1800s at the time. Bumped again, further out of
    # proportion with normal deck-fetch time, because Moxfield commander
    # resolution (_resolve_moxfield_commanders, user-requested) now runs in
    # the same job: a *first* full resolution across this project's real
    # ~6,300-deck Moxfield cache is itself ~1.7h (confirmed via live
    # sampling - no bulk lookup endpoint exists, only a paced per-ID one).
    # This is a one-time cost (app.models.discover.MoxfieldCommanderCache
    # makes every later sync only pay for genuinely new commanders), so a
    # generous ceiling here costs nothing once the cache is warm - no need
    # to shrink it back down later.
    get_queue("default").enqueue(sync_popular_decks, job_timeout=14400)
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

    # Kept separate from `warnings` below: only a source's own fetch failing
    # counts toward "every source failed" (FAILED status) - a commander-
    # resolution hiccup is real to report, but Moxfield's deck data itself
    # still landed fine, so it must not make an otherwise-successful sync
    # look like a total outage.
    errors: list[str] = []
    warnings: list[str] = []
    for source_name, fetch_fn in _SOURCES:
        try:
            decks = fetch_fn(settings.scryfall_user_agent)
        except Exception as exc:  # noqa: BLE001 - one source's failure must not abort the others
            errors.append(f"{source_name}: {exc}")
            continue

        if source_name == "moxfield":
            try:
                decks = _resolve_moxfield_commanders(db, decks, settings.scryfall_user_agent)
            except Exception as exc:  # noqa: BLE001 - commander names are an enrichment, not core sync data
                warnings.append(f"moxfield commander resolution: {exc}")

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
                        "commander_name": d.commander_name,
                        "has_primer": d.has_primer,
                        "deck_size": d.deck_size,
                        "theorycrafted": d.theorycrafted,
                        "comment_count": d.comment_count,
                        "bookmark_count": d.bookmark_count,
                        "deck_updated_at": d.deck_updated_at,
                        "tags": d.tags,
                    }
                    for d in decks
                ],
            )
        db.commit()

    total = db.scalar(select(func.count()).select_from(PopularDeck))
    all_messages = errors + warnings

    if errors and len(errors) == len(_SOURCES):
        state.status = DeckDiscoverySyncStatus.failed.value
        state.error_message = "; ".join(all_messages)[:1024]
    else:
        state.status = DeckDiscoverySyncStatus.current.value
        state.error_message = "; ".join(all_messages)[:1024] if all_messages else None
    state.deck_count = total or 0
    state.finished_at = datetime.now(UTC)
    db.commit()

    if errors and len(errors) == len(_SOURCES):
        raise RuntimeError(state.error_message)

    return state


_COMMANDER_CACHE_FLUSH_EVERY = 25


def _resolve_moxfield_commanders(
    db: Session, decks: list[PopularDeckEntry], user_agent: str
) -> list[PopularDeckEntry]:
    """Fills in `commander_name` on every Moxfield entry that has a
    `main_card_id`, using MoxfieldCommanderCache for already-known names and
    moxfield.iter_resolved_commander_names for the rest (paced, potentially
    slow the first time - see that function's own docstring). Commits the
    cache periodically (not just at the end) so a mid-run crash or worker
    restart - see CLAUDE.md gotcha #29, a real, routine occurrence during
    dev, not hypothetical - only loses the current partial batch, not every
    resolution made so far in this run.
    """
    known: dict[str, str] = {
        row.main_card_id: row.name
        for row in db.execute(select(MoxfieldCommanderCache.main_card_id, MoxfieldCommanderCache.name))
    }
    main_card_ids = {d.main_card_id for d in decks if d.main_card_id}

    newly_resolved: dict[str, str] = {}
    for i, (main_card_id, name) in enumerate(
        moxfield.iter_resolved_commander_names(main_card_ids, user_agent, known=known), start=1
    ):
        newly_resolved[main_card_id] = name
        db.add(MoxfieldCommanderCache(main_card_id=main_card_id, name=name))
        if i % _COMMANDER_CACHE_FLUSH_EVERY == 0:
            db.commit()
    db.commit()

    known.update(newly_resolved)
    return [replace(d, commander_name=known.get(d.main_card_id)) if d.main_card_id else d for d in decks]


def search_archidekt_by_commander(db: Session, commander_name: str, settings: Settings | None = None) -> list[PopularDeck]:
    """Live, on-demand proxy to Archidekt's real `commanderName` search
    filter (see archidekt.search_by_commander for why this can't be a local
    cache lookup like Moxfield's - Archidekt's search API never returns a
    commander field, only accepts one as a filter). Only ever called on an
    explicit user action (Enter/submit, not on every keystroke - see
    app/api/discover.py), never from the regular sync, to avoid hitting
    Archidekt live on casual browsing.

    Returns already-cached PopularDeck rows whose external_id matched the
    live search - a deck Archidekt returns but this project hasn't synced
    yet is silently not included (no partial/uncached row is fabricated),
    matching "no fake success": every returned row has real, complete local
    metadata (color identity, bracket, price if already computed), not a
    thin live-only stub.
    """
    settings = settings or get_settings()
    matched_ids = archidekt.search_by_commander(commander_name, settings.scryfall_user_agent)
    if not matched_ids:
        return []
    stmt = (
        select(PopularDeck)
        .where(PopularDeck.source == "archidekt", PopularDeck.external_id.in_(matched_ids))
        .order_by(PopularDeck.view_count.desc())
    )
    return list(db.scalars(stmt))


def list_popular_decks(
    db: Session,
    *,
    sort: str = "views",
    color_identity: str | None = None,
    source: str | None = None,
    bracket: int | None = None,
    q: str | None = None,
    has_primer: bool | None = None,
    min_deck_size: int | None = None,
    exclude_theorycrafted: bool = False,
    updated_after_days: int | None = None,
    tag: str | None = None,
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
    `q`, when given, is a case-insensitive substring match against the deck
    *name* OR the (Moxfield-only, separately resolved) `commander_name` -
    see app.source_adapters.moxfield.resolve_commander_names and
    MoxfieldCommanderCache for why only Moxfield has a real, permanently
    stored commander name; Archidekt commander search is a separate live
    query (search_archidekt_by_commander below), not part of this function.
    `has_primer`, `min_deck_size`, `updated_after_days`, and `tag` filter
    against real fields both sources' search APIs already return (verified
    live - see CLAUDE.md). `exclude_theorycrafted` drops Archidekt decks
    real-flagged as never actually built/played (Moxfield has no such
    concept, so its rows are never excluded by this filter regardless).
    """
    order_column = {"likes": PopularDeck.like_count, "comments": PopularDeck.comment_count, "bookmarks": PopularDeck.bookmark_count}.get(
        sort, PopularDeck.view_count
    )
    stmt = select(PopularDeck).order_by(order_column.desc())
    if source:
        stmt = stmt.where(PopularDeck.source == source)
    if bracket is not None:
        stmt = stmt.where(PopularDeck.bracket == bracket)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(PopularDeck.name.ilike(needle) | PopularDeck.commander_name.ilike(needle))
    if has_primer is not None:
        stmt = stmt.where(PopularDeck.has_primer == has_primer)
    if min_deck_size is not None:
        stmt = stmt.where(PopularDeck.deck_size >= min_deck_size)
    if exclude_theorycrafted:
        stmt = stmt.where(PopularDeck.theorycrafted.is_not(True))
    if updated_after_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=updated_after_days)
        stmt = stmt.where(PopularDeck.deck_updated_at >= cutoff)
    if tag and tag.strip():
        stmt = stmt.where(PopularDeck.tags.contains([tag.strip()]))
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
