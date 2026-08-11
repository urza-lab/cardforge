from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PopularDeckPriceRequest(BaseModel):
    price_profile_id: int
    collection_id: int | None = None


class DeckDiscoverySyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    started_at: datetime | None
    finished_at: datetime | None
    deck_count: int
    error_message: str | None


class PopularDeckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    name: str
    author: str | None
    source_url: str
    format: str
    view_count: int
    like_count: int
    color_identity: list[str] | None
    bracket: int | None
    synced_at: datetime
    coverage_percent: float | None
    missing_cost: Decimal | None
    missing_cost_currency: str | None
    unpriced_missing_count: int | None
    priced_at: datetime | None
