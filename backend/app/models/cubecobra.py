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

from sqlalchemy import ForeignKey, Integer, String, func
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
