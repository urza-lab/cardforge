from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CubeDiscoverySyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    started_at: datetime | None
    finished_at: datetime | None
    cube_count: int
    error_message: str | None


class PopularCubeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_username: str | None
    source_url: str
    card_count: int
    like_count: int
    tags: list[str] | None
    num_decks: int | None
    date_last_updated: datetime | None
    synced_at: datetime
    imported_list_id: int | None
    import_error: str | None
    import_attempted_at: datetime | None
