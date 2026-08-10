from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.settings import UserSettings
from app.models.user import DEFAULT_USER_ID

VALID_COMPARISON_MODES = {"oracle", "printing"}
VALID_CARD_NAME_LANGUAGES = {"de", "en"}

# card_name_language's valid values include None ("auto" - see
# app.models.settings.UserSettings), so update_settings can't use "None means
# don't touch this field" for it the way it does for the other two settings.
# This sentinel distinguishes "caller didn't mention this field" from
# "caller explicitly wants it cleared to auto".
UNSET: Any = object()


class InvalidComparisonModeError(ValueError):
    pass


class InvalidCardNameLanguageError(ValueError):
    pass


def get_settings(db: Session, user_id: int = DEFAULT_USER_ID) -> UserSettings:
    settings = db.get(UserSettings, user_id)
    if settings is None:
        raise RuntimeError(f"user_settings row for user {user_id} is missing - has the migration been applied?")
    return settings


def update_settings(
    db: Session,
    *,
    default_comparison_mode: str | None = None,
    preferred_currency: str | None = None,
    card_name_language: str | None = UNSET,
    user_id: int = DEFAULT_USER_ID,
) -> UserSettings:
    settings = get_settings(db, user_id)

    if default_comparison_mode is not None:
        if default_comparison_mode not in VALID_COMPARISON_MODES:
            raise InvalidComparisonModeError(
                f"default_comparison_mode must be one of {sorted(VALID_COMPARISON_MODES)}, "
                f"got '{default_comparison_mode}'"
            )
        settings.default_comparison_mode = default_comparison_mode

    if preferred_currency is not None:
        settings.preferred_currency = preferred_currency.strip().upper()

    if card_name_language is not UNSET:
        if card_name_language is not None and card_name_language.lower() not in VALID_CARD_NAME_LANGUAGES:
            raise InvalidCardNameLanguageError(
                f"card_name_language must be one of {sorted(VALID_CARD_NAME_LANGUAGES)} or null (auto), "
                f"got '{card_name_language}'"
            )
        settings.card_name_language = card_name_language.lower() if card_name_language else None

    db.commit()
    db.refresh(settings)
    return settings
