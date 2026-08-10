from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    synced_at: datetime
