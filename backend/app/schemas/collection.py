from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class CollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class CollectionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_name: str
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    quantity: int
    foil: bool
    language: str | None
    condition: str | None
    purchase_price: Decimal | None
    purchase_currency: str | None
    scryfall_id: str | None
    source_import_id: int | None
    created_at: datetime
    updated_at: datetime
