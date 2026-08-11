"""Popular-deck discovery cache — "browse real popular Commander decks and
one-click import them," user-requested after the 7-phase plan. See
SOURCE_ADAPTERS.md. `PopularDeck` is a local cache, not queried live on
every page view: Moxfield's public search API rate-limited this project
during development after only a handful of rapid requests, so browsing
reads from here and a separate sync job (mirrors
app/source_adapters/scryfall.py's own sync pattern) refreshes it on demand.
Archidekt was added as a second source the same way — see
app.services.discover_service.run_discovery_sync and SOURCE_ADAPTERS.md.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# id=1 always exists (seeded by this table's migration) - same "single
# stable row to update in place" pattern as app.models.scryfall.
# SYNC_STATE_ID, so sync status has nowhere else to race against itself.
DISCOVERY_SYNC_STATE_ID = 1


class DeckDiscoverySyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


class PopularDeck(Base):
    __tablename__ = "popular_decks"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_popular_decks_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="moxfield")  # "moxfield" or "archidekt"
    external_id: Mapped[str] = mapped_column(String(64))  # Moxfield's own publicId
    name: Mapped[str] = mapped_column(String(256))
    author: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(512))
    format: Mapped[str] = mapped_column(String(32))  # "commander" only, for now
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    color_identity: Mapped[list[str] | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DeckDiscoverySyncState(Base):
    __tablename__ = "deck_discovery_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=DeckDiscoverySyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    deck_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
