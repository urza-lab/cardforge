from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ListBuildabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    list_id: int
    name: str
    list_type: str
    coverage_percent: float
    is_fully_buildable: bool


class LeverageCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    oracle_id: str | None
    scryfall_card_id: str | None
    quantity_needed: int
    lists_newly_buildable: int
    total_coverage_gain: float


class DashboardSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collection_distinct_items: int
    collection_total_quantity: int
    collection_resolved_count: int
    list_count: int
    lists_fully_buildable: int
    average_coverage_percent: float
    scryfall_sync_status: str
    scryfall_card_count: int
    scryfall_source_updated_at: datetime | None
    mtgjson_sync_status: str
    mtgjson_price_count: int
    list_buildability: list[ListBuildabilityRead]
    top_leverage: list[LeverageCandidateRead]
