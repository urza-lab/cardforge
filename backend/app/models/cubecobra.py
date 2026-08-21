"""CubeCobra popular-cube discovery cache — "browse real popular cubes and
one-click import them," the cube-side counterpart to app/models/discover.py's
`PopularDeck` (Commander decks, Moxfield/Archidekt). Kept as its own table
rather than folded into `PopularDeck`: a cube isn't a deck (no color
identity/format the same way, has card_count/tags instead), and CubeCobra's
own real popularity signal is `likeCount` only (no separate view count the
way Moxfield/Archidekt each expose). Same "local cache, synced on demand"
reasoning as PopularDeck - CubeCobra's search is paginated via a DynamoDB
`lastKey` cursor (see app/source_adapters/cubecobra.py), not cheap enough to
query live on every browse request either.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# id=1 always exists (seeded by this table's migration) - same pattern as
# app.models.discover.DISCOVERY_SYNC_STATE_ID.
CUBE_DISCOVERY_SYNC_STATE_ID = 1


class CubeDiscoverySyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


class PopularCube(Base):
    __tablename__ = "popular_cubes"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)  # CubeCobra's own real cube id
    short_id: Mapped[str] = mapped_column(String(128))  # CubeCobra's human-friendly slug, used in source_url
    name: Mapped[str] = mapped_column(String(256))
    owner_username: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(512))
    card_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    # Real quality/popularity signals beyond likeCount (user-requested) -
    # see app/source_adapters/cubecobra.py's PopularCubeEntry docstring for
    # why these two and not a comment count or star rating (neither exists
    # in CubeCobra's real search response, confirmed live).
    num_decks: Mapped[int | None] = mapped_column(Integer)
    date_last_updated: Mapped[datetime | None] = mapped_column()
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # Real quality signals user-requested for efficient filtering *without*
    # narrowing the crawl itself (a likeCount/numDecks stop-threshold was
    # considered and rejected live - confirmed real data at 150k+ cubes deep
    # showed everything is still 0-like/0-deck there, meaning a threshold
    # would have skipped exactly the obscure-but-real cubes this whole
    # feature exists to reach). Found by dumping a full raw cube object
    # (not just the subset already mapped above) - CubeCobra has no
    # separate `hasPrimer` flag the way Moxfield/Archidekt do, so a real,
    # non-empty `description` is the closest equivalent proxy for "the
    # owner put in real effort," confirmed live (a real cube like "MTGO
    # Vintage Cube" has a real description; the "X's New Cube"-named,
    # 0-like/0-deck cubes deep in the crawl have none).
    description: Mapped[str | None] = mapped_column(Text)
    featured: Mapped[bool] = mapped_column(default=False)
    keywords: Mapped[list[str] | None] = mapped_column(JSONB)
    version: Mapped[int | None] = mapped_column(Integer)
    owner_follower_count: Mapped[int | None] = mapped_column(Integer)

    # Server-side import tracking (user-requested) - a browse page reload
    # or a routine resync must not lose "already imported"/"failed, retry"
    # state the way ephemeral React state did before. ON DELETE SET NULL:
    # if the user deletes the imported CardList directly, this cube should
    # go back to showing "Import" rather than a dead link. Preserved across
    # `run_cube_discovery_sync`'s delete+reinsert by snapshotting/restoring
    # keyed on `external_id` - same pattern as scryfall.py's run_bulk_sync
    # preserving price_observations across a full scryfall_cards wipe (see
    # CLAUDE.md gotcha #19) - without that, this whole feature would reset
    # to "not imported" on every routine sync.
    imported_list_id: Mapped[int | None] = mapped_column(ForeignKey("card_lists.id", ondelete="SET NULL"))
    import_error: Mapped[str | None] = mapped_column(String(1024))
    import_attempted_at: Mapped[datetime | None] = mapped_column()


class CubeDiscoverySyncState(Base):
    __tablename__ = "cube_discovery_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=CubeDiscoverySyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    cube_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))


CUBE_FULL_SCRAPE_STATE_ID = 1


class CubeFullScrapeStatus(str, enum.Enum):
    inactive = "INACTIVE"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class CubeFullScrapeState(Base):
    """User-requested: unlike the regular, bounded, popularity-sorted sync
    above (CubeDiscoverySyncState/POPULAR_CUBES_PAGES), this tracks a real
    full-catalog walk of CubeCobra's search API to genuine exhaustion (its
    `lastKey` cursor running out) - the only way to ever reach an obscure,
    0-like cube, which no depth of "top N by popularity" pagination can
    (confirmed live against a real such cube - see CLAUDE.md). Kept as a
    separate single-row table (not extra columns on CubeDiscoverySyncState)
    since the two are genuinely different operations that can be triggered
    independently and shouldn't share one status field.

    No `total_cubes`/`eta` field on purpose - CubeCobra exposes no count
    endpoint, so there's no reliable way to know the real total in advance;
    only `cubes_found`/`pages_fetched` (what's actually been seen so far)
    and timestamps (from which a caller can derive a real, honest average
    time per cube/page) are tracked, never a fabricated estimate of what's
    left.
    """

    __tablename__ = "cube_full_scrape_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=CubeFullScrapeStatus.inactive.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    # Updated on every page, independent of started_at/finished_at - lets a
    # status poll show "still actively running" vs. possibly stuck, without
    # waiting for the whole (open-ended, possibly very long) scrape to finish.
    last_progress_at: Mapped[datetime | None] = mapped_column()
    cubes_found: Mapped[int] = mapped_column(default=0)
    pages_fetched: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
    # CubeCobra's own DynamoDB pagination cursor (JSON-serialized), updated
    # after every page - user-requested/found live: without this, retrying
    # a failed/interrupted scrape always re-walked from page 1, real network
    # requests included, discarding no data (upserts never duplicate) but
    # wasting real time re-covering already-known ground before ever
    # reaching new territory past the previous failure point. `Text`, not a
    # bounded VARCHAR - unlike the other string fields here (see gotcha #40),
    # this one has no real column-width precedent to size against, and
    # getting it wrong the same way would silently break resume instead of
    # just one row's display data.
    last_key: Mapped[str | None] = mapped_column(Text)


CUBE_FULL_IMPORT_STATE_ID = 1


class CubeFullImportStatus(str, enum.Enum):
    inactive = "INACTIVE"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class CubeFullImportState(Base):
    """User-requested: a real, resumable bulk *import* (download each cube's
    real card list and create a CardList row) over a filtered subset of the
    already-cached `PopularCube` pool - distinct from CubeFullScrapeState
    above, which only crawls/caches CubeCobra's search metadata and never
    downloads a single card list. See app.services.cube_discover_service
    `run_full_cube_import` for the real candidate-selection query.

    Unlike the scrape, the candidate set here is a deterministic query over
    data CardForge already has locally - so `total_candidates` (unlike the
    scrape's cubes_found/pages_fetched-only design) can be a real, honest
    upfront count, making a genuine percentage-based progress bar possible.
    `last_cube_id` is the resume cursor (candidates are walked in a stable
    `ORDER BY id ASC`) - same "persist progress every unit of work, resume
    from exactly there instead of restarting" reasoning as the scrape's own
    `last_key`, since this job is expected to run for many hours across
    tens of thousands of real per-cube network fetches and must survive a
    worker restart/redeploy without losing already-imported cubes or
    re-downloading them.
    """

    __tablename__ = "cube_full_import_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=CubeFullImportStatus.inactive.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    last_progress_at: Mapped[datetime | None] = mapped_column()
    total_candidates: Mapped[int] = mapped_column(default=0)
    imported_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)  # already imported before this job reached them
    last_cube_id: Mapped[int | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(String(1024))

    # User-requested filters (2026-08-21, after the earlier default-scope
    # run imported 82,309 of 90,932 candidates - see CLAUDE.md): stored on
    # the state row, not passed as job args, so a resumed/retriggered run
    # keeps using the same scope the user chose at the last trigger call
    # (app.services.cube_discover_service.trigger_full_import writes these
    # on every trigger, run_full_cube_import reads them back instead of the
    # module-level defaults). `filter_max_total` is a plain safety ceiling
    # on how many candidates this logical job will ever process - not a
    # strict "N most popular" ranking (candidates are still walked in the
    # same stable `id ASC` order as always, for resumability), so it's
    # described honestly as that in the UI rather than implying an exact
    # popularity-sorted top-N.
    filter_min_card_count: Mapped[int] = mapped_column(default=180)
    filter_max_card_count: Mapped[int | None] = mapped_column()
    filter_require_description: Mapped[bool] = mapped_column(default=False)
    filter_top_n: Mapped[int] = mapped_column(default=10_000)
    filter_max_total: Mapped[int | None] = mapped_column()
