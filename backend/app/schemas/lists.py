from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.comparison import MissingCardRead


class CardListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    list_type: str  # "deck" | "cube"


class CardListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    list_type: str
    source_url: str | None
    created_at: datetime
    updated_at: datetime


class CardListItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_name: str
    # Not an ORM column - always overwritten by the API layer via
    # display_name_service before the response goes out (see app/api/lists.py).
    display_name: str = ""
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    quantity: int
    section: str
    category: str | None
    tags: list[str] | None
    foil: bool
    language: str | None
    scryfall_id: str | None
    resolved_oracle_id: str | None
    resolved_scryfall_card_id: str | None
    resolved_at: datetime | None
    source_import_id: int | None
    created_at: datetime
    updated_at: datetime


class ListImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    raw_data: dict[str, Any]
    mapped_data: dict[str, Any] | None
    status: str
    error_reason: str | None


class ListImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_id: int
    source_type: str
    original_filename: str | None
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    imported_rows: int
    duplicate_of_import_id: int | None
    created_at: datetime
    confirmed_at: datetime | None


class ListImportPreviewResponse(ListImportRead):
    rows: list[ListImportRowRead]
    is_likely_duplicate: bool


class ListImportConfirmRequest(BaseModel):
    skip_bad_rows: bool = False


class ListComparisonResponse(BaseModel):
    mode: str
    total_required_cards: int
    total_required_quantity: int
    total_owned_quantity: int
    coverage_percent: float
    is_fully_buildable: bool
    missing: list[MissingCardRead]
