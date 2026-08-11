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

from sqlalchemy import Integer, String, func
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
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class CubeDiscoverySyncState(Base):
    __tablename__ = "cube_discovery_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=CubeDiscoverySyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    cube_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
