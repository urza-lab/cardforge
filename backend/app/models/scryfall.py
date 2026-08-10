"""Local mirror of Scryfall's "all_cards" bulk data — see SOURCE_ADAPTERS.md
and ARCHITECTURE.md "Documented default decisions" for why a single
denormalized table (one row per printing) is enough for both oracle-mode and
printing-mode comparison, instead of separate oracle/printing tables.

Uses `all_cards`, not the smaller `default_cards` (Phase 3's original
choice) — `default_cards` omits a printing's non-English version entirely
when an English version of the same card exists, which meant `printed_name`
(the localized display name — see app.services.display_name_service, Phase
4) was only ever available for the small set of cards printed exclusively
in one non-English language.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# id=1 always exists (seeded by the Phase 3 migration, same pattern as
# app.models.user.DEFAULT_USER_ID) so sync status has a single stable row to
# update in place rather than a growing history table Phase 3 doesn't need.
SYNC_STATE_ID = 1


class ScryfallSyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


class ScryfallCard(Base):
    __tablename__ = "scryfall_cards"
    __table_args__ = (Index("ix_scryfall_cards_set_collector", "set_code", "collector_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # Scryfall's printing id (UUID)
    oracle_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)  # canonical English name, always present
    # The name as actually printed on this card, only set when it differs
    # from `name` (i.e. lang != "en") - see display_name_service.
    printed_name: Mapped[str | None] = mapped_column(String(256))
    set_code: Mapped[str] = mapped_column(String(16))
    set_name: Mapped[str] = mapped_column(String(128))
    collector_number: Mapped[str] = mapped_column(String(32))
    lang: Mapped[str] = mapped_column(String(8), index=True)
    layout: Mapped[str] = mapped_column(String(32))
    mana_cost: Mapped[str | None] = mapped_column(String(64))
    cmc: Mapped[float | None] = mapped_column(Float)
    type_line: Mapped[str | None] = mapped_column(String(256))
    oracle_text: Mapped[str | None] = mapped_column(Text)
    colors: Mapped[list[str] | None] = mapped_column(JSONB)
    color_identity: Mapped[list[str] | None] = mapped_column(JSONB)
    rarity: Mapped[str | None] = mapped_column(String(16))
    foil: Mapped[bool] = mapped_column(Boolean, default=False)
    nonfoil: Mapped[bool] = mapped_column(Boolean, default=False)
    released_at: Mapped[str | None] = mapped_column(String(10))  # ISO date, kept as text - never computed on
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ScryfallSyncState(Base):
    """Single-row status of the local bulk-data mirror. Only ever updated
    after a sync attempt actually finishes (success or failure) — never set
    to CURRENT speculatively, per ARCHITECTURE.md's "no fake success" rule.
    """

    __tablename__ = "scryfall_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=ScryfallSyncStatus.not_started.value)
    bulk_data_type: Mapped[str] = mapped_column(String(32), default="all_cards")
    # Scryfall's own "updated_at" for the bulk file, i.e. how fresh the data
    # we downloaded actually is - distinct from `finished_at` (when *we*
    # finished processing it).
    source_updated_at: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    card_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
