"""EDHREC synthesized-deck cache — a different shape from `PopularDeck`
(app/models/discover.py) on purpose: EDHREC has no hosted decklists to link
to, only per-commander card-recommendation statistics (see
app/source_adapters/edhrec.py). A "deck" here is computed by this app
(top N cards per category up to that commander's own real average
composition, e.g. "24 creatures, 35 lands"), not authored by a real person,
so it's kept in its own table/tab rather than mixed into `PopularDeck` -
user-requested after evaluating the shape difference (see ARCHITECTURE.md
"Documented default decisions").
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# id=1 always exists (seeded by this table's migration) - same pattern as
# app.models.discover.DISCOVERY_SYNC_STATE_ID / app.models.scryfall.SYNC_STATE_ID.
EDHREC_SYNC_STATE_ID = 1


class EdhrecSyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


class SynthesizedDeck(Base):
    __tablename__ = "edhrec_synthesized_decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    commander_slug: Mapped[str] = mapped_column(String(128), unique=True)
    commander_name: Mapped[str] = mapped_column(String(256))
    rank: Mapped[int] = mapped_column(Integer)  # EDHREC's own "Past 2 Years" popularity rank
    num_decks: Mapped[int] = mapped_column(Integer, default=0)  # real EDHREC deck count for this commander
    color_identity: Mapped[list[str] | None] = mapped_column(JSONB)
    card_count: Mapped[int] = mapped_column(Integer, default=0)  # synthesized card count - may be <99 if a category's real pool ran thin
    # A ready-to-import text decklist (app/parsers/list_text.py format,
    # "Commander: X" + one card name per line) built at sync time - importing
    # just replays this through the existing text-import pipeline, no live
    # EDHREC fetch at import time.
    deck_text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(512))  # edhrec.com page, attribution only - not machine-refetchable as a deck
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class EdhrecSyncState(Base):
    __tablename__ = "edhrec_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=EdhrecSyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    deck_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
