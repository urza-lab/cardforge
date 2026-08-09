from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.settings import UserSettings
from app.models.user import DEFAULT_USER_ID

VALID_COMPARISON_MODES = {"oracle", "printing"}


class InvalidComparisonModeError(ValueError):
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

    db.commit()
    db.refresh(settings)
    return settings
