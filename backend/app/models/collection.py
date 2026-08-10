from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.imports import Import
    from app.models.user import User


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_collections_user_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    # First collection created for a user is marked default so single-user UIs
    # (which don't ask "which collection?") have an unambiguous target.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="collections")
    items: Mapped[list[CollectionItem]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    # passive_deletes=True: don't have the ORM SELECT+UPDATE(SET NULL) every
    # Import row when a Collection is deleted (its default behavior without
    # this) - imports.collection_id is NOT NULL, so that would fail outright.
    # Trust the FK's own ON DELETE CASCADE (see the initial migration) to
    # remove them in the same statement instead.
    imports: Mapped[list[Import]] = relationship(back_populates="collection", passive_deletes=True)


class CollectionItem(Base):
    """A single owned printing/quantity, as committed from a confirmed import.

    Fields are stored exactly as parsed (Phase 2). `scryfall_id` is the
    *user-supplied* identifier when present in the source file (e.g.
    ManaBox's own "Scryfall ID" column) — it is not validated against
    anything at import time. `resolved_oracle_id`/`resolved_scryfall_card_id`
    (Phase 3) are populated separately by matching this row against the
    local `scryfall_cards` mirror (see app/services/scryfall_resolution.py)
    and are what the comparison engine actually reads.
    """

    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    card_name: Mapped[str] = mapped_column(String(256))
    set_code: Mapped[str | None] = mapped_column(String(16))
    set_name: Mapped[str | None] = mapped_column(String(128))
    collector_number: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column()
    foil: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    language: Mapped[str | None] = mapped_column(String(8))
    condition: Mapped[str | None] = mapped_column(String(8))
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    purchase_currency: Mapped[str | None] = mapped_column(String(8))
    scryfall_id: Mapped[str | None] = mapped_column(String(36))
    # Nullable + ON DELETE SET NULL: deleting the Import audit record must
    # never cascade-delete the collection items it produced.
    source_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL"), index=True
    )
    # Phase 3 resolution against the local Scryfall mirror (scryfall_cards).
    # oracle_id groups all printings of "the same card" (oracle-mode
    # comparison); scryfall_card_id is the exact printing, when determinable
    # (printing-mode comparison). Either can be null if resolution found no
    # confident match — the comparison engine treats those as "unresolved".
    resolved_oracle_id: Mapped[str | None] = mapped_column(String(36), index=True)
    resolved_scryfall_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("scryfall_cards.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    collection: Mapped[Collection] = relationship(back_populates="items")
