"""Deck/cube data model (Phase 4).

See ARCHITECTURE.md "Documented default decisions" for why manual list
import (this model + app/parsers/list_text.py + app/services/list_import_
service.py) landed in Phase 4 rather than waiting for Phase 5 — Phase 5 is
scoped to the Moxfield/Archidekt *public URL* adapters and refresh system
specifically, not manual import, and Phase 4's detail pages need something
to show.

`ListImport`/`ListImportRow` deliberately duplicate the shape of
`Import`/`ImportRow` (app/models/imports.py) rather than generalizing one
shared table for both collections and lists: the two pipelines write
different target row shapes (CollectionItem has condition/price;
CardListItem has section/category/tags), and keeping them fully separate
means a bug in one can never touch the other.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ListType(str, enum.Enum):
    deck = "deck"
    cube = "cube"


class ListItemSection(str, enum.Enum):
    mainboard = "mainboard"
    commander = "commander"
    companion = "companion"
    sideboard = "sideboard"
    maybeboard = "maybeboard"
    considering = "considering"


class ListImportSourceType(str, enum.Enum):
    text = "text"
    json = "json"


class ListImportStatus(str, enum.Enum):
    previewed = "previewed"
    confirmed = "confirmed"
    partially_confirmed = "partially_confirmed"
    aborted = "aborted"


class ListImportRowStatus(str, enum.Enum):
    ok = "ok"
    error = "error"


class CardList(Base):
    __tablename__ = "card_lists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_card_lists_user_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    list_type: Mapped[str] = mapped_column(String(16))  # "deck" | "cube"
    # Phase 5: set for lists synced from a Moxfield/Archidekt URL; null for
    # manually-imported lists (all of them, as of Phase 4).
    source_url: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship()
    items: Mapped[list[CardListItem]] = relationship(
        back_populates="card_list", cascade="all, delete-orphan"
    )
    # passive_deletes=True: same fix as app.models.collection.Collection.imports
    # - list_imports.list_id is NOT NULL, so the ORM's default "SET NULL on
    # delete" behavior fails; trust the FK's own ON DELETE CASCADE instead.
    imports: Mapped[list[ListImport]] = relationship(back_populates="card_list", passive_deletes=True)


class CardListItem(Base):
    __tablename__ = "card_list_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("card_lists.id", ondelete="CASCADE"), index=True)
    card_name: Mapped[str] = mapped_column(String(256))
    set_code: Mapped[str | None] = mapped_column(String(16))
    set_name: Mapped[str | None] = mapped_column(String(128))
    collector_number: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column()
    # "mainboard" | "commander" | "companion" | "sideboard" | "maybeboard" |
    # "considering" - see IMPORT_FORMATS.md "Text lists".
    section: Mapped[str] = mapped_column(String(16), default=ListItemSection.mainboard.value)
    category: Mapped[str | None] = mapped_column(String(64))  # cube category, e.g. "Ramp" (Phase 4 UI, coverage TBD)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    foil: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    language: Mapped[str | None] = mapped_column(String(8))
    scryfall_id: Mapped[str | None] = mapped_column(String(36))
    resolved_oracle_id: Mapped[str | None] = mapped_column(String(36), index=True)
    resolved_scryfall_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("scryfall_cards.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column()
    source_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("list_imports.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    card_list: Mapped[CardList] = relationship(back_populates="items")


class ListImport(Base):
    __tablename__ = "list_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("card_lists.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(String(256))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ListImportStatus.previewed.value)
    total_rows: Mapped[int] = mapped_column(default=0)
    valid_rows: Mapped[int] = mapped_column(default=0)
    error_rows: Mapped[int] = mapped_column(default=0)
    imported_rows: Mapped[int] = mapped_column(default=0)
    duplicate_of_import_id: Mapped[int | None] = mapped_column(ForeignKey("list_imports.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column()

    user: Mapped[User] = relationship()
    card_list: Mapped[CardList] = relationship(back_populates="imports")
    rows: Mapped[list[ListImportRow]] = relationship(
        back_populates="list_import", cascade="all, delete-orphan", order_by="ListImportRow.row_number"
    )


class ListImportRow(Base):
    __tablename__ = "list_import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_import_id: Mapped[int] = mapped_column(ForeignKey("list_imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column()
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    mapped_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    error_reason: Mapped[str | None] = mapped_column(String(512))

    list_import: Mapped[ListImport] = relationship(back_populates="rows")
