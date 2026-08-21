"""Popular-cube discovery: sync orchestration (mirrors
app/services/discover_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/cubecobra.py
for the actual sync work and app/models/cubecobra.py for why this is a
separate cache from `PopularDeck`.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.cubecobra import (
    CUBE_DISCOVERY_SYNC_STATE_ID,
    CUBE_FULL_IMPORT_STATE_ID,
    CUBE_FULL_SCRAPE_STATE_ID,
    CubeDiscoverySyncState,
    CubeDiscoverySyncStatus,
    CubeFullImportState,
    CubeFullImportStatus,
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
                        "description": c.description,
                        "featured": c.featured,
                        "keywords": c.keywords,
                        "version": c.version,
                        "owner_follower_count": c.owner_follower_count,
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
                            "description": c.description,
                            "featured": c.featured,
                            "keywords": c.keywords,
                            "version": c.version,
                            "owner_follower_count": c.owner_follower_count,
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
                        "description": stmt.excluded.description,
                        "featured": stmt.excluded.featured,
                        "keywords": stmt.excluded.keywords,
                        "version": stmt.excluded.version,
                        "owner_follower_count": stmt.excluded.owner_follower_count,
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


# Real, user-requested bulk-import candidate rule (see CLAUDE.md) - a cube
# qualifies once it has real substance (>= 180 cards, raised from the
# original 40 after the user asked to exclude undersized cubes - 180 is
# below every common real cube size CLAUDE.md's own live distribution check
# found (360/540/180/450 are the most common exact sizes), so it only
# excludes genuinely small/incomplete cubes, not the smaller end of
# legitimate ones) AND is either popular enough (top N by one of
# CubeCobra's 3 real popularity signals - there is no real "views" field,
# confirmed live) or has other evidence of being a real, cared-for cube (an
# owner with real followers, or a written description) rather than one of
# the many auto-named, unmaintained cubes the full catalog scrape also
# picked up.
FULL_IMPORT_MIN_CARD_COUNT = 180
FULL_IMPORT_TOP_N_PER_CATEGORY = 10_000
FULL_IMPORT_MIN_FOLLOWERS = 5


def _full_import_candidates_select(
    min_id: int | None = None,
    *,
    min_card_count: int = FULL_IMPORT_MIN_CARD_COUNT,
    max_card_count: int | None = None,
    require_description: bool = False,
    top_n: int = FULL_IMPORT_TOP_N_PER_CATEGORY,
):
    """Ranks the whole `popular_cubes` table by each of the 3 real
    popularity signals CubeCobra exposes (like_count/num_decks/
    owner_follower_count - "most viewed" was requested but CubeCobra has no
    real per-cube view counter, confirmed live by dumping a full raw cube
    object: the only `views` key is a display-layout config, not a
    counter).

    User-requested filters (2026-08-21, after the default-scope run
    imported 82,309 of 90,932 candidates - see CLAUDE.md): `min_card_count`/
    `max_card_count` bound real card count; `require_description`, when
    True, *replaces* the popularity-OR-description qualification below with
    a strict "must have a real description" requirement (AND'd with the
    card-count bounds) instead of just being one of several ways to
    qualify - the whole point of checking this box is to *narrow* scope to
    curated-looking cubes, which the old "description OR popular" logic
    would silently defeat by still admitting every popular cube regardless.
    When False, the original behavior is unchanged: a cube qualifies if
    it's in the top `top_n` of any of the 3 popularity ranks, has
    >= FULL_IMPORT_MIN_FOLLOWERS followers, or has a real description.
    Window functions are recomputed on every call rather than cached -
    acceptable since this only runs once per (re)trigger, not per
    candidate.
    """
    likes_rank = func.rank().over(order_by=PopularCube.like_count.desc().nulls_last())
    decks_rank = func.rank().over(order_by=PopularCube.num_decks.desc().nulls_last())
    followers_rank = func.rank().over(order_by=PopularCube.owner_follower_count.desc().nulls_last())
    ranked = select(
        PopularCube.id,
        PopularCube.card_count,
        PopularCube.description,
        PopularCube.owner_follower_count,
        likes_rank.label("likes_rank"),
        decks_rank.label("decks_rank"),
        followers_rank.label("followers_rank"),
    ).subquery("ranked_cubes")

    conditions = [ranked.c.card_count >= min_card_count]
    if max_card_count is not None:
        conditions.append(ranked.c.card_count <= max_card_count)

    if require_description:
        conditions.append(ranked.c.description.is_not(None))
    else:
        conditions.append(
            or_(
                ranked.c.likes_rank <= top_n,
                ranked.c.decks_rank <= top_n,
                ranked.c.followers_rank <= top_n,
                ranked.c.owner_follower_count >= FULL_IMPORT_MIN_FOLLOWERS,
                ranked.c.description.is_not(None),
            )
        )
    if min_id is not None:
        conditions.append(ranked.c.id > min_id)
    return select(ranked.c.id).where(*conditions).order_by(ranked.c.id)


def get_full_import_state(db: Session) -> CubeFullImportState:
    state = db.get(CubeFullImportState, CUBE_FULL_IMPORT_STATE_ID)
    if state is None:
        raise RuntimeError("cube_full_import_state row is missing - has the migration been applied?")
    return state


def trigger_full_import(
    db: Session,
    *,
    min_card_count: int = FULL_IMPORT_MIN_CARD_COUNT,
    max_card_count: int | None = None,
    require_description: bool = False,
    top_n: int = FULL_IMPORT_TOP_N_PER_CATEGORY,
    max_total: int | None = None,
) -> CubeFullImportState:
    """Starts (or resumes, if `state.last_cube_id` is already set from a
    prior interrupted/failed run) the real bulk import. Unlike
    trigger_full_scrape, the candidate set here is a deterministic query
    over data already in the database, so a real, honest `total_candidates`
    can be computed upfront - recomputed on every trigger (including a
    resume) so it reflects the current cache, not a stale snapshot.
    `imported_count`/`failed_count`/`skipped_count`/`last_cube_id` are
    deliberately NOT reset here - they're cumulative across the whole
    logical job (which may span several worker restarts/redeploys), not
    per-trigger-call, so the progress bar never jumps backwards.

    The 5 filter params (user-requested, 2026-08-21) are written onto the
    state row on *every* trigger call, including a resume - so retriggering
    with a different scope changes what happens next without needing a
    separate "edit filters" endpoint, and `run_full_cube_import` (which
    actually walks candidates, possibly much later in a background job)
    reads them back from there rather than needing them passed as RQ job
    args. `max_total` folds into `total_candidates` here (capped at
    whichever is smaller) so the progress bar reflects the real ceiling
    this run will actually stop at.
    """
    state = get_full_import_state(db)
    if state.status == CubeFullImportStatus.running.value:
        raise SyncAlreadyInProgressError

    from app.workers.jobs import run_full_cube_import_job

    state.filter_min_card_count = min_card_count
    state.filter_max_card_count = max_card_count
    state.filter_require_description = require_description
    state.filter_top_n = top_n
    state.filter_max_total = max_total

    total = (
        db.scalar(
            select(func.count()).select_from(
                _full_import_candidates_select(
                    min_card_count=min_card_count,
                    max_card_count=max_card_count,
                    require_description=require_description,
                    top_n=top_n,
                ).subquery()
            )
        )
        or 0
    )
    if max_total is not None:
        total = min(total, max_total)

    # Same "no principled way to size this" reasoning as trigger_full_scrape
    # - a real per-cube fetch is ~2.2-2.6s (measured live), so tens of
    # thousands of candidates is realistically a multi-day job; the timeout
    # is a safety net against a truly stuck job, not an estimate.
    get_queue("default").enqueue(run_full_cube_import_job, job_timeout=604800)
    state.status = CubeFullImportStatus.running.value
    if state.started_at is None:
        state.started_at = datetime.now(UTC)
    state.finished_at = None
    state.total_candidates = total
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_full_cube_import(db: Session, *, user_id: int = DEFAULT_USER_ID) -> CubeFullImportState:
    """Real, resumable bulk import (user-requested) over the candidate set
    `_full_import_candidates_select` defines - downloads each candidate's
    real card list via the existing single-cube `import_popular_cube` (same
    fetch-and-parse path, same per-cube failure handling: a failed cube is
    recorded as `import_error` on its own row and the walk continues, never
    aborting the whole job over one bad cube). Walks candidates in a stable
    `ORDER BY id ASC` and persists `last_cube_id` after every cube - a
    worker restart/redeploy (a real, routine occurrence during this
    project's dev sessions - see gotchas #16/#18/#29/#38) resumes exactly
    where it left off instead of restarting from the first candidate or
    re-downloading cubes already imported.

    No extra pacing/delay is added between cubes beyond each fetch's own
    real network+parse latency (~2.2-2.6s, measured live) - a real 808-cube
    sequential bulk import earlier in this project hit zero CubeCobra rate
    limiting at that same natural, unthrottled pace (see CLAUDE.md); this
    job can run far longer in wall-clock time but at the same real
    per-request rate, not a faster one.

    Reads its filter scope (min/max card count, require_description, top_n,
    max_total) from the state row rather than taking them as parameters -
    see `trigger_full_import` for why (state is the one thing both the API
    request and this later-run background job can both see).
    `filter_max_total`, when set, stops the walk once the *cumulative*
    processed count (imported+skipped+failed, across this whole logical
    job, not just this call) reaches it - candidates are still walked in
    the same `id ASC` order as always, so this is a hard ceiling on total
    work done, not a guarantee of processing the N globally most popular
    cubes first.
    """
    state = get_full_import_state(db)
    resume_from = state.last_cube_id
    candidate_ids = list(
        db.scalars(
            _full_import_candidates_select(
                min_id=resume_from,
                min_card_count=state.filter_min_card_count,
                max_card_count=state.filter_max_card_count,
                require_description=state.filter_require_description,
                top_n=state.filter_top_n,
            )
        )
    )

    state.status = CubeFullImportStatus.running.value
    if state.started_at is None:
        state.started_at = datetime.now(UTC)
    state.finished_at = None
    state.error_message = None
    db.commit()

    try:
        for cube_id in candidate_ids:
            state = get_full_import_state(db)
            processed_so_far = state.imported_count + state.skipped_count + state.failed_count
            if state.filter_max_total is not None and processed_so_far >= state.filter_max_total:
                break

            cube = db.get(PopularCube, cube_id)
            if cube is None:
                continue
            was_already_imported = cube.imported_list_id is not None

            result_cube = import_popular_cube(db, cube_id, user_id=user_id)

            state = get_full_import_state(db)
            if result_cube.imported_list_id is not None:
                if was_already_imported:
                    state.skipped_count += 1
                else:
                    state.imported_count += 1
            else:
                state.failed_count += 1
            state.last_cube_id = cube_id
            state.last_progress_at = datetime.now(UTC)
            db.commit()

        state = get_full_import_state(db)
        state.status = CubeFullImportStatus.completed.value
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_full_import_state(db)
        state.status = CubeFullImportStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1000


def list_popular_cubes(
    db: Session,
    *,
    sort: str = "likes",
    has_description: bool | None = None,
    featured: bool | None = None,
    min_followers: int | None = None,
    min_card_count: int | None = None,
    max_card_count: int | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[PopularCube]:
    """`has_description`/`featured`/`min_followers`/`min_card_count`/
    `max_card_count` filter against real signals found live in CubeCobra's
    own search response (user-requested, see PopularCube's own model
    comment) - deliberately kept as filters over the *already fully-
    crawled* cache rather than ever narrowing what the crawl itself
    fetches, so an obscure-but-real cube (0 likes, small niche cube size)
    is never skipped just because it isn't "popular" - only whether it's
    *shown* here is affected. `min_card_count` in particular targets a
    real, live-confirmed junk cluster: 6.6% of the real cache (13,196
    cubes) has exactly 1 card - clearly broken/placeholder entries, not
    real cubes - a much more reliable "is this junk" signal than
    `has_description` turned out to be (97% of *all* cubes, including
    plenty of real ones, have no description at all).
    """
    order_column: InstrumentedAttribute[int] | InstrumentedAttribute[int | None]
    if sort == "cards":
        order_column = PopularCube.card_count
    elif sort == "decks":
        order_column = PopularCube.num_decks
    elif sort == "followers":
        order_column = PopularCube.owner_follower_count
    else:
        order_column = PopularCube.like_count
    stmt = select(PopularCube).order_by(order_column.desc().nulls_last())
    if has_description is not None:
        stmt = stmt.where(PopularCube.description.is_not(None) if has_description else PopularCube.description.is_(None))
    if featured is not None:
        stmt = stmt.where(PopularCube.featured == featured)
    if min_followers is not None:
        stmt = stmt.where(PopularCube.owner_follower_count >= min_followers)
    if min_card_count is not None:
        stmt = stmt.where(PopularCube.card_count >= min_card_count)
    if max_card_count is not None:
        stmt = stmt.where(PopularCube.card_count <= max_card_count)
    # Real bug found live, user-reported browser out-of-memory: this
    # endpoint had no limit at all, fine while the cache was ~1,000-18,000
    # rows but the full-catalog scrape (see run_full_cube_scrape) grew it to
    # 200,000+ - returning every matching row as one JSON payload into an
    # unvirtualized frontend table crashed the tab. A browse UI never needs
    # more than a bounded top-N of the current sort anyway.
    stmt = stmt.limit(min(limit, MAX_LIST_LIMIT))
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

    # `card_lists.name` is String(128) - a real cube name (or the
    # disambiguated "name (short_id)" form) can exceed that, confirmed live
    # by the full-import job crashing outright on a real ~150-char cube name
    # with an uncaught StringDataRightTruncation, taking down the whole job
    # instead of just that one cube (see CLAUDE.md). Truncated the same way
    # gotcha #34/#40's `_truncate` already handles this class of bug
    # elsewhere in this project.
    target_name = _truncate(cube.name, 128)
    assert target_name is not None  # cube.name is a non-nullable str column
    if name_is_ambiguous:
        target_name = _truncate(f"{cube.name} ({cube.short_id})", 128)
        assert target_name is not None
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
    try:
        card_list = list_service.create_list(db, name=target_name, list_type="cube", user_id=user_id)
        import_record, _deck_name = list_import_service.create_preview_from_url(
            db, card_list=card_list, url=cube.source_url, user_agent=settings.scryfall_user_agent, user_id=user_id
        )
        list_import_service.confirm_import(db, import_record, skip_bad_rows=True)
    except Exception as exc:  # noqa: BLE001 - any failure here must be recorded, not silently swallowed
        # A failure inside create_list itself (e.g. the truncation bug this
        # whole try/except was widened to cover) leaves the session's
        # transaction aborted - roll back before any further query, and
        # `card_list` was never successfully assigned in that specific case.
        db.rollback()
        if "card_list" in locals():
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
