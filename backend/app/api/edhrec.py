from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.edhrec import EdhrecSyncStatusRead, SynthesizedDeckRead
from app.services import edhrec_service

router = APIRouter(prefix="/api/edhrec", tags=["edhrec"])


@router.get("/decks", response_model=list[SynthesizedDeckRead])
def list_synthesized_decks(
    sort: str = "num_decks", color_identity: str | None = None, db: Session = Depends(get_db)
) -> list[SynthesizedDeckRead]:
    decks = edhrec_service.list_synthesized_decks(db, sort=sort, color_identity=color_identity)
    return [SynthesizedDeckRead.model_validate(d) for d in decks]


@router.get("/decks/status", response_model=EdhrecSyncStatusRead)
def get_sync_status(db: Session = Depends(get_db)) -> EdhrecSyncStatusRead:
    return EdhrecSyncStatusRead.model_validate(edhrec_service.get_sync_state(db))


@router.post("/decks/sync", response_model=EdhrecSyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> EdhrecSyncStatusRead:
    try:
        state = edhrec_service.trigger_sync(db)
    except edhrec_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="an EDHREC sync is already in progress") from exc
    return EdhrecSyncStatusRead.model_validate(state)
