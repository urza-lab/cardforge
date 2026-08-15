from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


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
    commander_name: str | None
    has_primer: bool
    deck_size: int | None
    theorycrafted: bool | None
    comment_count: int
    bookmark_count: int | None
    deck_updated_at: datetime | None
    tags: list[str] | None

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: Any) -> Any:
        """Real bug found live: some stored `PopularDeck.tags` rows contain
        Archidekt tag-assignment objects (`{"id": ..., "tag": <numeric id>,
        "name": "Sacrifice", "position": ...}`) instead of plain strings -
        Archidekt's real search response shape isn't consistently a flat
        string list the way it was when this field was first added (see
        CLAUDE.md). The real tag name is available under `name`, so it's
        extracted rather than dropped; an entry with neither a plain string
        nor a real `name` is skipped rather than fabricated. This crashed
        `GET /api/discover/decks` with a 500 for every request until fixed,
        since one bad row anywhere in the result set broke the whole list.
        """
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                normalized.append(item["name"])
        return normalized or None
