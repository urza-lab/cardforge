from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.pricing import MtgjsonSyncStatusRead
from app.services import mtgjson_service

router = APIRouter(prefix="/api/mtgjson", tags=["mtgjson"])


@router.get("/status", response_model=MtgjsonSyncStatusRead)
def get_status(db: Session = Depends(get_db)) -> MtgjsonSyncStatusRead:
    return MtgjsonSyncStatusRead.model_validate(mtgjson_service.get_sync_state(db))


@router.post("/sync", response_model=MtgjsonSyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> MtgjsonSyncStatusRead:
    try:
        state = mtgjson_service.trigger_sync(db)
    except mtgjson_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="an MTGJSON price sync is already in progress") from exc
    return MtgjsonSyncStatusRead.model_validate(state)
