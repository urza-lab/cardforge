"""Popular-cube discovery: sync orchestration (mirrors
app/services/discover_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/cubecobra.py
for the actual sync work and app/models/cubecobra.py for why this is a
separate cache from `PopularDeck`.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.cubecobra import (
    CUBE_DISCOVERY_SYNC_STATE_ID,
    CUBE_FULL_SCRAPE_STATE_ID,
    CubeDiscoverySyncState,
    CubeDiscoverySyncStatus,
    CubeFullScrapeState,
    CubeFullScrapeStatus,
    PopularCube,
)
from app.models.lists import CardList, CardListItem
from app.models.user import DEFAULT_USER_ID
from app.services import list_import_service, list_service
from app.source_adapters import cubecobra


def _truncate(value: str | None, max_length: int) -> str | None:
    """Defensively bounds a field to its own PopularCube column width
    before insert - same reasoning and shape as
    app.services.list_import_service._truncate (see CLAUDE.md gotcha #34):
    a real cube's name/username can just be longer than the column allows,
    confirmed live by a real `StringDataRightTruncation` 34,554 cubes into
    a real full-catalog scrape (deep, unpopular cubes this project had
    never fetched before - the bounded, popularity-limited sync never hit
    this in its ~1,000-1,400-cube range). Truncating rather than rejecting
    the whole row keeps one long value from aborting an otherwise-good
    batch, matching the "one malformed row shouldn't sink the rest"
    principle gotcha #34 established.
    """
    if value is None:
        return None
    return value[:max_length]


class SyncAlreadyInProgressError(Exception):
    pass


class CubeNotFoundError(Exception):
    pass


def get_sync_state(db: Session) -> CubeDiscoverySyncState:
    state = db.get(CubeDiscoverySyncState, CUBE_DISCOVERY_SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("cube_discovery_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> CubeDiscoverySyncState:
    state = get_sync_state(db)
    if state.status == CubeDiscoverySyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - same lazy-import reasoning as
    # discover_service.trigger_sync (avoids a hard API->worker import cycle).
    from app.workers.jobs import sync_popular_cubes

    get_queue("default").enqueue(sync_popular_cubes, job_timeout=600)
    state.status = CubeDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_cube_discovery_sync(db: Session, settings: Settings | None = None) -> CubeDiscoverySyncState:
    settings = settings or get_settings()
    state = get_sync_state(db)

    state.status = CubeDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        cubes = cubecobra.fetch_popular_cubes(settings.scryfall_user_agent)

        # Snapshot server-side import tracking (imported_list_id/
        # import_error/import_attempted_at, see app/models/cubecobra.py)
        # before the wipe, keyed by CubeCobra's own stable external_id -
        # restored below so "already imported"/"failed, retry" survives a
        # routine resync instead of silently resetting to "not imported"
        # every time (same snapshot/restore shape as scryfall.py's
        # run_bulk_sync preserving price_observations, see CLAUDE.md
        # gotcha #19).
        preserved_import_state = {
            row.external_id: (row.imported_list_id, row.import_error, row.import_attempted_at)
            for row in db.scalars(select(PopularCube))
        }

        db.execute(delete(PopularCube))
        if cubes:
            db.execute(
                insert(PopularCube),
                [
                    {
                        "external_id": _truncate(c.external_id, 64),
                        "short_id": _truncate(c.short_id, 128),
                        "name": _truncate(c.name, 256),
                        "owner_username": _truncate(c.owner_username, 128),
                        "source_url": _truncate(c.source_url, 512),
                        "card_count": c.card_count,
                        "like_count": c.like_count,
                        "tags": c.tags,
                        "num_decks": c.num_decks,
                        "date_last_updated": c.date_last_updated,
                    }
                    for c in cubes
                ],
            )

        for external_id, (imported_list_id, import_error, import_attempted_at) in preserved_import_state.items():
            if imported_list_id is None and import_error is None and import_attempted_at is None:
                continue
            db.execute(
                update(PopularCube)
                .where(PopularCube.external_id == external_id)
                .values(
                    imported_list_id=imported_list_id,
                    import_error=import_error,
                    import_attempted_at=import_attempted_at,
                )
            )

        state.status = CubeDiscoverySyncStatus.current.value
        state.cube_count = len(cubes)
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_sync_state(db)
        state.status = CubeDiscoverySyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


def get_full_scrape_state(db: Session) -> CubeFullScrapeState:
    state = db.get(CubeFullScrapeState, CUBE_FULL_SCRAPE_STATE_ID)
    if state is None:
        raise RuntimeError("cube_full_scrape_state row is missing - has the migration been applied?")
    return state


def trigger_full_scrape(db: Session) -> CubeFullScrapeState:
    state = get_full_scrape_state(db)
    if state.status == CubeFullScrapeStatus.running.value:
        raise SyncAlreadyInProgressError

    from app.workers.jobs import run_full_cubecobra_scrape

    # No real total is knowable in advance (CubeCobra has no count endpoint)
    # so there's no principled way to size a timeout against "how long the
    # whole thing takes" the way other syncs' job_timeout values are sized -
    # a generous, effectively-non-binding ceiling (7 days) is used instead,
    # purely as a safety net against a truly stuck job, not a real estimate.
    get_queue("default").enqueue(run_full_cubecobra_scrape, job_timeout=604800)
    state.status = CubeFullScrapeStatus.running.value
    state.started_at = datetime.now(UTC)
    state.finished_at = None
    state.last_progress_at = None
    state.cubes_found = 0
    state.pages_fetched = 0
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_full_cube_scrape(db: Session, settings: Settings | None = None) -> CubeFullScrapeState:
    """The real, user-requested "pull everything CubeCobra will give us"
    scrape - walks app.source_adapters.cubecobra.iter_all_cubes to genuine
    exhaustion (its lastKey cursor running out), not the bounded, top-N-by-
    popularity walk `run_cube_discovery_sync` above does. Upserts each page
    by `external_id` (PopularCube's own unique constraint) rather than the
    regular sync's delete-then-reinsert - this can run far longer than that
    one page's own request, and a worker restart/crash partway through
    should never lose cubes already found, nor ever create duplicates of a
    cube seen more than once across pages or across scrapes.

    Resumes from `state.last_key` (CubeCobra's own pagination cursor,
    persisted after every page - see CubeFullScrapeState's own docstring)
    if one is already stored, rather than always restarting from page 1 -
    user-requested/found live: two real multi-hour attempts both died on a
    transient network error thousands of pages in, and retrying always
    re-walked the same already-known ground first before ever reaching new
    territory, wasting real hours re-covering it. Only cleared back to None
    on a genuinely successful completion (nothing left to resume from);
    left in place on failure specifically so the next trigger picks up
    here instead of page 1.
    """
    settings = settings or get_settings()
    state = get_full_scrape_state(db)

    resume_key: object | None = json.loads(state.last_key) if state.last_key else None

    state.status = CubeFullScrapeStatus.running.value
    state.started_at = datetime.now(UTC)
    state.finished_at = None
    state.error_message = None
    db.commit()

    try:
        for page, new_last_key in cubecobra.iter_all_cubes(settings.scryfall_user_agent, start_key=resume_key):
            if page:
                now = datetime.now(UTC)
                stmt = pg_insert(PopularCube).values(
                    [
                        {
                            "external_id": _truncate(c.external_id, 64),
                            "short_id": _truncate(c.short_id, 128),
                            "name": _truncate(c.name, 256),
                            "owner_username": _truncate(c.owner_username, 128),
                            "source_url": _truncate(c.source_url, 512),
                            "card_count": c.card_count,
                            "like_count": c.like_count,
                            "tags": c.tags,
                            "num_decks": c.num_decks,
                            "date_last_updated": c.date_last_updated,
                            "synced_at": now,
                        }
                        for c in page
                    ]
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[PopularCube.external_id],
                    set_={
                        "short_id": stmt.excluded.short_id,
                        "name": stmt.excluded.name,
                        "owner_username": stmt.excluded.owner_username,
                        "source_url": stmt.excluded.source_url,
                        "card_count": stmt.excluded.card_count,
                        "like_count": stmt.excluded.like_count,
                        "tags": stmt.excluded.tags,
                        "num_decks": stmt.excluded.num_decks,
                        "date_last_updated": stmt.excluded.date_last_updated,
                        "synced_at": stmt.excluded.synced_at,
                        # imported_list_id/import_error/import_attempted_at
                        # deliberately left untouched by this upsert - same
                        # "don't reset real import-tracking state on a
                        # routine resync" reasoning as run_cube_discovery_sync's
                        # snapshot/restore above, just achieved for free here
                        # by simply never including them in `set_`.
                    },
                )
                db.execute(stmt)

            state.cubes_found += len(page)
            state.pages_fetched += 1
            state.last_progress_at = datetime.now(UTC)
            state.last_key = json.dumps(new_last_key) if new_last_key else None
            db.commit()

        state.status = CubeFullScrapeStatus.completed.value
        state.finished_at = datetime.now(UTC)
        state.last_key = None  # genuine exhaustion reached - nothing left to resume from
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_full_scrape_state(db)
        state.status = CubeFullScrapeStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


def list_popular_cubes(db: Session, *, sort: str = "likes") -> list[PopularCube]:
    order_column: InstrumentedAttribute[int] | InstrumentedAttribute[int | None]
    if sort == "cards":
        order_column = PopularCube.card_count
    elif sort == "decks":
        order_column = PopularCube.num_decks
    else:
        order_column = PopularCube.like_count
    stmt = select(PopularCube).order_by(order_column.desc().nulls_last())
    return list(db.scalars(stmt))


def import_popular_cube(db: Session, cube_id: int, *, user_id: int = DEFAULT_USER_ID) -> PopularCube:
    """One-click/retry import for a single cached cube (user-requested):
    creates the CardList and runs the same create-preview-confirm sequence
    the frontend used to orchestrate itself over three separate calls, but
    persists the outcome directly on this cube's own row (imported_list_id
    on success, import_error on failure) so a page reload - or a later
    resync, see run_cube_discovery_sync's snapshot/restore above - doesn't
    lose "already imported" or "failed, here's why, retry" state the way
    ephemeral browser state did before.

    On any failure *after* the CardList was already created, that now-
    orphaned empty list is deleted rather than left behind with no items
    and no source_type/source_url. This is a real bug found live: a bulk
    "select all" import of the full CubeCobra cache left exactly this kind
    of dangling empty list behind for every cube whose fetch/confirm step
    failed partway through (network hiccup, CubeCobra rate limiting, an
    empty/malformed CSV) - see CLAUDE.md.

    A failure is recorded as data (cube.import_error set, HTTP 200), not
    raised as an HTTP error - a failed import is an expected, retryable
    outcome here, not a server fault. Only "cube not found" raises.
    """
    cube = db.get(PopularCube, cube_id)
    if cube is None:
        raise CubeNotFoundError(cube_id)

    if cube.imported_list_id is not None and list_service.get_list(db, cube.imported_list_id, user_id=user_id):
        return cube  # already imported and the list still exists - nothing to do

    # `card_lists` has a real (user_id, name) uniqueness constraint - a
    # name collision here is expected, not a corner case, for any cube
    # already imported before this row-level tracking existed (confirmed
    # live: a bulk "select all" import of 588 cubes had already claimed
    # most of these exact names).
    #
    # But a same name is NOT reliable proof of "same cube": two distinct
    # real CubeCobra cubes can share an identical display name (confirmed
    # live against real data - e.g. 5 different real cubes all named
    # "Commander Cube", by 5 different owners). Blindly adopting the first
    # same-named list wrongly attributed one cube's real import to a
    # completely different cube (two live cases found and corrected - see
    # CLAUDE.md). So: adoption (or cleaning up an orphaned empty same-named
    # list to re-attempt under the same name) only happens when this
    # cube's name is *unambiguous* - no other cached cube currently shares
    # it. When it's ambiguous, this cube gets its own disambiguated list
    # name instead of ever touching a list that might belong to a
    # different real cube.
    name_is_ambiguous = (
        db.scalar(
            select(func.count(func.distinct(PopularCube.external_id))).where(PopularCube.name == cube.name)
        )
        or 0
    ) > 1

    target_name = cube.name
    if name_is_ambiguous:
        target_name = f"{cube.name} ({cube.short_id})"
    else:
        existing = db.scalars(
            select(CardList).where(
                CardList.user_id == user_id, CardList.name == cube.name, CardList.list_type == "cube"
            )
        ).first()
        if existing is not None:
            has_items = db.scalar(
                select(func.count()).select_from(CardListItem).where(CardListItem.list_id == existing.id)
            )
            if has_items:
                cube.imported_list_id = existing.id
                cube.import_error = None
                cube.import_attempted_at = datetime.now(UTC)
                db.commit()
                db.refresh(cube)
                return cube
            list_service.delete_list(db, existing)

    settings = get_settings()
    card_list = list_service.create_list(db, name=target_name, list_type="cube", user_id=user_id)
    try:
        import_record, _deck_name = list_import_service.create_preview_from_url(
            db, card_list=card_list, url=cube.source_url, user_agent=settings.scryfall_user_agent, user_id=user_id
        )
        list_import_service.confirm_import(db, import_record, skip_bad_rows=True)
    except Exception as exc:  # noqa: BLE001 - any failure here must be recorded, not silently swallowed
        list_service.delete_list(db, card_list)
        cube = db.get(PopularCube, cube_id)
        assert cube is not None  # just loaded above; nothing else can delete a PopularCube mid-request
        cube.import_error = str(exc)[:1024]
        cube.import_attempted_at = datetime.now(UTC)
        db.commit()
        db.refresh(cube)
        return cube

    cube = db.get(PopularCube, cube_id)
    assert cube is not None
    cube.imported_list_id = card_list.id
    cube.import_error = None
    cube.import_attempted_at = datetime.now(UTC)
    db.commit()
    db.refresh(cube)
    return cube
