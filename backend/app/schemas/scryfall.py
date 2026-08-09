from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScryfallSyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    bulk_data_type: str
    source_updated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    card_count: int
    error_message: str | None
