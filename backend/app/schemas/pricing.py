from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MtgjsonSyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    price_count: int
    error_message: str | None


class PriceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=1, max_length=8)
    provider_priority: list[str]
    prefer_foil: bool = False


class PriceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    provider_priority: list[str] | None = None
    prefer_foil: bool | None = None
    is_default: bool | None = None


class PriceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    currency: str
    provider_priority: list[str]
    prefer_foil: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ManualPriceSetRequest(BaseModel):
    scryfall_card_id: str = Field(min_length=1, max_length=36)
    currency: str = Field(min_length=1, max_length=8)
    foil: bool = False
    price: Decimal = Field(gt=0)


class PriceObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scryfall_card_id: str
    provider: str
    currency: str
    foil: bool
    price: Decimal
    observed_at: datetime


class CardPriceRead(BaseModel):
    """Resolved single price for a card under a given price profile - the
    provider that actually matched (or null if none of the profile's
    providers had a price for this card/currency/foil combination).
    """

    scryfall_card_id: str
    currency: str
    foil: bool
    price: Decimal | None
    provider: str | None


class PricedMissingCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    oracle_id: str | None
    missing_quantity: int
    unit_price: Decimal | None
    provider: str | None


class BudgetLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    oracle_id: str | None
    unit_price: Decimal
    provider: str
    missing_quantity: int
    affordable_quantity: int
    line_total: Decimal


class BudgetResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    budget: Decimal
    lines: list[BudgetLineRead]
    total_spent: Decimal
    remaining_budget: Decimal
    fully_covered: bool
    unpriced: list[PricedMissingCardRead]
