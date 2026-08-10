"""Price cache (Phase 6) — see PRICING.md.

`PriceObservation` holds the *latest known* price per (card, provider,
currency, foil) — not a price-history time series. Each provider's sync
replaces its own rows wholesale (same "delete then bulk insert" pattern as
`app/source_adapters/scryfall.py`'s card mirror sync), so a row's
`observed_at` is simply "when this value was last confirmed still current",
not a point in a longer series. A dedicated history table is a real
possible future feature but nothing today reads price trends over time.

`PriceProfile` is a named provider-priority + currency + foil preference
used to resolve one actual number for a card (see
`app/services/pricing_service.py` `resolve_price`) — the same
default-bootstrap pattern as the default `Collection`
(`app/services/collection_service.py`), not a hardcoded singleton, since
README.md's "price profiles" (plural) implies more than one is expected
eventually (e.g. a cheap-proxy-friendly profile vs a "real paper price"
one).
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class PriceProvider(str, enum.Enum):
    scryfall = "scryfall"
    mtgjson = "mtgjson"
    manual = "manual"


class PriceSyncStatus(str, enum.Enum):
    not_started = "NOT_STARTED"
    fetching = "FETCHING"
    current = "CURRENT"
    failed = "FAILED"


# Every price profile ever bootstrapped starts with this order: prefer a
# user's own manual override, then MTGJSON (broader currency coverage - see
# PRICING.md), then Scryfall (piggybacks the mirror sync we already run, so
# it's the one source guaranteed to be populated even if MTGJSON sync was
# never triggered).
DEFAULT_PROVIDER_PRIORITY = [PriceProvider.manual.value, PriceProvider.mtgjson.value, PriceProvider.scryfall.value]
DEFAULT_PRICE_PROFILE_NAME = "Default"


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint(
            "scryfall_card_id", "provider", "currency", "foil", name="uq_price_observations_card_provider_currency_foil"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scryfall_card_id: Mapped[str] = mapped_column(
        ForeignKey("scryfall_cards.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))  # PriceProvider value
    currency: Mapped[str] = mapped_column(String(8))  # ISO 4217, e.g. "USD" / "EUR"
    foil: Mapped[bool] = mapped_column(Boolean, default=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    observed_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PriceProfile(Base):
    __tablename__ = "price_profiles"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_price_profiles_user_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    # Ordered list of PriceProvider values, first match wins - see
    # app.services.pricing_service.resolve_price.
    provider_priority: Mapped[list[str]] = mapped_column(JSONB, default=list)
    prefer_foil: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship()


class PriceSyncState(Base):
    """Per-provider sync status, same FETCHING/CURRENT/FAILED shape as
    `app.models.scryfall.ScryfallSyncState` (kept as a separate table rather
    than merged into it — that one is Scryfall's own card-mirror sync
    specifically, seeded with a single fixed-id row; this one is keyed by
    provider so it generalizes to any future provider that needs a
    real background sync job. Scryfall's own price extraction piggybacks on
    ScryfallSyncState instead of getting a row here — it's not a separate
    sync, just a side effect of the card mirror sync already tracked there.
    `manual` never gets a row - there's nothing to sync, prices are entered
    directly.
    """

    __tablename__ = "price_sync_state"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)  # PriceProvider value
    status: Mapped[str] = mapped_column(String(32), default=PriceSyncStatus.not_started.value)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    price_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024))
