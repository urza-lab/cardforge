from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.comparison.types import ComparisonResult
from app.pricing.budget import BudgetResult, PricedMissingCard
from app.schemas.comparison import MissingCardRead
from app.schemas.pricing import BudgetResultRead, PricedMissingCardRead


class CardListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    list_type: str  # "deck" | "cube"


class CardListUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class CardListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    list_type: str
    source_url: str | None
    source_type: str | None
    refresh_status: str | None
    refresh_error: str | None
    last_refreshed_at: datetime | None
    # Not an ORM column - computed by app.services.list_refresh_service.is_stale
    # and filled in by the API layer (see app/api/lists.py).
    is_stale: bool = False
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
    source_url: str | None
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
    # Only set for URL-sourced previews (the real deck name the source
    # reported, e.g. Moxfield's/Archidekt's own "name" field) - not an ORM
    # column, filled in by the API layer from DeckFetchResult.deck_name
    # (app/source_adapters/common.py), which was previously fetched and
    # silently discarded. Lets the frontend auto-name a bulk-imported list
    # from the real deck name instead of a user-typed placeholder.
    deck_name: str | None = None


class ListImportConfirmRequest(BaseModel):
    skip_bad_rows: bool = False


class ListImportUrlRequest(BaseModel):
    list_id: int
    url: str = Field(min_length=1, max_length=512)


class ListComparisonResponse(BaseModel):
    mode: str
    total_required_cards: int
    total_required_quantity: int
    total_owned_quantity: int
    coverage_percent: float
    is_fully_buildable: bool
    missing: list[MissingCardRead]
    # Both null unless a price_profile_id query param was passed (pricing
    # every missing card costs extra DB round-trips - see
    # pricing_service.resolve_cheapest_price_for_oracle - so it's opt-in,
    # not computed on every comparison call). `budget` is additionally null
    # if a price_profile_id was given but no budget cap was.
    priced_missing: list[PricedMissingCardRead] | None = None
    budget: BudgetResultRead | None = None

    @classmethod
    def from_result(
        cls,
        result: ComparisonResult,
        priced_missing: list[PricedMissingCard] | None = None,
        budget: BudgetResult | None = None,
    ) -> ListComparisonResponse:
        """Shared by GET /api/lists/{id}/comparison and GET
        /api/shopping-list - both compute a plain ComparisonResult, then
        optionally enrich it with pricing (see
        app.services.pricing_service.price_and_budget_missing_cards).
        """
        return cls(
            mode=result.mode,
            total_required_cards=result.total_required_cards,
            total_required_quantity=result.total_required_quantity,
            total_owned_quantity=result.total_owned_quantity,
            coverage_percent=result.coverage_percent,
            is_fully_buildable=result.is_fully_buildable,
            missing=[
                MissingCardRead(
                    name=m.name,
                    oracle_id=m.oracle_id,
                    required_quantity=m.required_quantity,
                    owned_quantity=m.owned_quantity,
                    missing_quantity=m.missing_quantity,
                )
                for m in result.missing
            ],
            priced_missing=[PricedMissingCardRead.model_validate(p) for p in priced_missing]
            if priced_missing is not None
            else None,
            budget=BudgetResultRead.model_validate(budget) if budget is not None else None,
        )
