"""Real official Commander preconstructed decks, from MTGJSON's bulk deck
data — the "best coverage" source, materially different from `PopularDeck`/
`PopularCube`/`SynthesizedDeck`: instead of ranking by popularity, this
source's whole point is that we already have every deck's *real, complete*
card list (via MTGJSON's own `identifiers.scryfallOracleId` per card, see
app/source_adapters/mtgjson_precons.py), so real buildability coverage
against the user's own collection can be computed directly and cheaply
(app.comparison.engine.compare is a pure in-memory function - no per-deck
DB round-trip) instead of needing an import or a per-deck external fetch
the way "how much of this Moxfield/Archidekt/CubeCobra deck would I already
own" would.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PRECON_SYNC_STATE_ID = 1


class PreconSyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


class PreconDeck(Base):
    __tablename__ = "precon_decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(128), unique=True)  # MTGJSON's own deck file identifier
    name: Mapped[str] = mapped_column(String(256))
    commander_names: Mapped[list[str]] = mapped_column(JSONB)
    release_date: Mapped[str | None] = mapped_column(String(10))
    source_url: Mapped[str] = mapped_column(String(512))  # the real WotC article MTGJSON's own DeckList cites
    card_count: Mapped[int] = mapped_column(Integer, default=0)
    # {"name": str, "oracle_id": str | None, "quantity": int} per card - used
    # to build a RequiredCard list for app.comparison.engine.compare at read
    # time (cheap, pure, no DB round-trip), so coverage is always computed
    # fresh against the user's *current* collection, never a stale cached %.
    cards: Mapped[list[dict]] = mapped_column(JSONB)
    # A ready-to-import CSV (name,quantity,scryfall_id,section) - see
    # app/source_adapters/mtgjson_precons.py. Importing replays this through
    # the existing upload-based text/CSV import pipeline, same as EDHREC's
    # deck_text, since there's no source URL to fetch-and-parse from at
    # import time the way Moxfield/Archidekt/CubeCobra decks have.
    deck_text: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PreconSyncState(Base):
    __tablename__ = "precon_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=PreconSyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    deck_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
