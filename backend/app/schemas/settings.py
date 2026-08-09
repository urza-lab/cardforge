from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_comparison_mode: str
    preferred_currency: str
    updated_at: datetime


class UserSettingsUpdate(BaseModel):
    default_comparison_mode: str | None = None
    preferred_currency: str | None = None
