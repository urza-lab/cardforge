from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.scryfall import ScryfallSyncStatusRead
from app.services import scryfall_service

router = APIRouter(prefix="/api/scryfall", tags=["scryfall"])


@router.get("/status", response_model=ScryfallSyncStatusRead)
def get_status(db: Session = Depends(get_db)) -> ScryfallSyncStatusRead:
    return ScryfallSyncStatusRead.model_validate(scryfall_service.get_sync_state(db))


@router.post("/sync", response_model=ScryfallSyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> ScryfallSyncStatusRead:
    try:
        state = scryfall_service.trigger_sync(db)
    except scryfall_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a Scryfall sync is already in progress") from exc
    return ScryfallSyncStatusRead.model_validate(state)
