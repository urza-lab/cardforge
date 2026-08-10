from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_comparison_mode: str
    preferred_currency: str
    card_name_language: str | None
    updated_at: datetime


class UserSettingsUpdate(BaseModel):
    default_comparison_mode: str | None = None
    preferred_currency: str | None = None
    # None is a meaningful value here ("auto" - see app.models.settings), so
    # the API layer checks `model_fields_set` to tell "omitted" from
    # "explicitly set to null" before passing this through to
    # settings_service.update_settings (which has its own UNSET sentinel for
    # the same reason).
    card_name_language: str | None = None
