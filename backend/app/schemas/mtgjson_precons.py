from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PreconSyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    started_at: datetime | None
    finished_at: datetime | None
    deck_count: int
    error_message: str | None


class PreconDeckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    name: str
    commander_names: list[str]
    release_date: str | None
    source_url: str
    card_count: int
    deck_text: str
    synced_at: datetime
    coverage_percent: float
    is_fully_buildable: bool
    missing_count: int
