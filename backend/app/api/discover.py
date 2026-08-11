from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.discover import DeckDiscoverySyncStatusRead, PopularDeckRead
from app.services import discover_service

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/decks", response_model=list[PopularDeckRead])
def list_popular_decks(
    sort: str = "views", color_identity: str | None = None, source: str | None = None, db: Session = Depends(get_db)
) -> list[PopularDeckRead]:
    decks = discover_service.list_popular_decks(db, sort=sort, color_identity=color_identity, source=source)
    return [PopularDeckRead.model_validate(d) for d in decks]


@router.get("/decks/status", response_model=DeckDiscoverySyncStatusRead)
def get_sync_status(db: Session = Depends(get_db)) -> DeckDiscoverySyncStatusRead:
    return DeckDiscoverySyncStatusRead.model_validate(discover_service.get_sync_state(db))


@router.post("/decks/sync", response_model=DeckDiscoverySyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> DeckDiscoverySyncStatusRead:
    try:
        state = discover_service.trigger_sync(db)
    except discover_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a popular-decks sync is already in progress") from exc
    return DeckDiscoverySyncStatusRead.model_validate(state)
