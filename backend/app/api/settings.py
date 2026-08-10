from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.settings import UserSettingsRead, UserSettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettingsRead)
def get_settings(db: Session = Depends(get_db)) -> UserSettingsRead:
    return UserSettingsRead.model_validate(settings_service.get_settings(db))


@router.put("", response_model=UserSettingsRead)
def update_settings(payload: UserSettingsUpdate, db: Session = Depends(get_db)) -> UserSettingsRead:
    # "card_name_language" omitted from the request body vs. explicitly sent
    # as null mean different things ("don't touch" vs. "reset to auto") -
    # model_fields_set is how pydantic tells those apart.
    card_name_language = (
        payload.card_name_language if "card_name_language" in payload.model_fields_set else settings_service.UNSET
    )
    try:
        settings = settings_service.update_settings(
            db,
            default_comparison_mode=payload.default_comparison_mode,
            preferred_currency=payload.preferred_currency,
            card_name_language=card_name_language,
        )
    except settings_service.InvalidComparisonModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except settings_service.InvalidCardNameLanguageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserSettingsRead.model_validate(settings)
