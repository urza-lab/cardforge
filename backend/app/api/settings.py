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
    try:
        settings = settings_service.update_settings(
            db,
            default_comparison_mode=payload.default_comparison_mode,
            preferred_currency=payload.preferred_currency,
        )
    except settings_service.InvalidComparisonModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserSettingsRead.model_validate(settings)
