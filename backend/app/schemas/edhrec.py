from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EdhrecSyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    started_at: datetime | None
    finished_at: datetime | None
    deck_count: int
    error_message: str | None


class SynthesizedDeckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    commander_slug: str
    commander_name: str
    rank: int
    num_decks: int
    color_identity: list[str] | None
    card_count: int
    deck_text: str
    source_url: str
    synced_at: datetime
