"""Per-user preferences (Phase 3). One row per user, 1:1 with `users`."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User

DEFAULT_COMPARISON_MODE = "oracle"
DEFAULT_PREFERRED_CURRENCY = "USD"


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # "oracle" | "printing" - see app.comparison.types.ComparisonMode. Used as
    # the Comparisons page's default so users who only ever compare one way
    # don't have to re-pick it every time.
    default_comparison_mode: Mapped[str] = mapped_column(String(16), default=DEFAULT_COMPARISON_MODE)
    # ISO 4217 currency code. Not yet read anywhere (pricing/budget features
    # are Phase 6) - stored now so the setting exists in one place from the
    # start rather than being bolted on later.
    preferred_currency: Mapped[str] = mapped_column(String(8), default=DEFAULT_PREFERRED_CURRENCY)
    # None = "auto": display each card in whatever language its own import
    # data says (see app.services.display_name_service). "de"/"en" forces
    # every card name to that language regardless of the item's own language,
    # falling back to the English name where no localized name is mirrored.
    card_name_language: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="settings")
