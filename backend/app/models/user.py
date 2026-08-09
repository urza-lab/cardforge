from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.imports import Import

# id=1 always exists (see migrations/versions/0001_initial_schema.py) so that
# single-user mode has a stable owner for collections/imports without a login
# flow. Multi-user mode (Phase 2+, CARDFORGE_AUTH_MODE=multi-user) adds more
# rows to this same table.
DEFAULT_USER_ID = 1


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    collections: Mapped[list[Collection]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    imports: Mapped[list[Import]] = relationship(back_populates="user", cascade="all, delete-orphan")
