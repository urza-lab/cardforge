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
    imports: Mapped[list[Import]] = relationship(back_populates="collection")


class CollectionItem(Base):
    """A single owned printing/quantity, as committed from a confirmed import.

    Fields are stored exactly as parsed (Phase 2) — resolving against the
    Scryfall printing database (matching by scryfall_id, or set_code +
    collector_number + name) is Phase 3's job. `scryfall_id` is kept here
    only as the *user-supplied* identifier when present in the source file.
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    collection: Mapped[Collection] = relationship(back_populates="items")
