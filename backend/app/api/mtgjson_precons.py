from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.mtgjson_precons import PreconDeckRead, PreconSyncStatusRead
from app.services import collection_service, precon_service

router = APIRouter(prefix="/api/precons", tags=["precons"])


@router.get("/decks", response_model=list[PreconDeckRead])
def list_precon_decks(
    collection_id: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PreconDeckRead]:
    """Ranked by real buildability coverage against `collection_id` (the
    default collection when omitted) - see precon_service module docstring
    for why this is computed live rather than served from a cached column.
    """
    resolved_collection_id = collection_id
    if resolved_collection_id is None:
        resolved_collection_id = collection_service.get_or_create_default_collection(db).id

    ranked = precon_service.list_precon_decks_with_coverage(db, collection_id=resolved_collection_id, limit=limit)
    return [
        PreconDeckRead(
            id=r.deck.id,
            file_name=r.deck.file_name,
            name=r.deck.name,
            commander_names=r.deck.commander_names,
            release_date=r.deck.release_date,
            source_url=r.deck.source_url,
            card_count=r.deck.card_count,
            deck_text=r.deck.deck_text,
            synced_at=r.deck.synced_at,
            coverage_percent=r.coverage_percent,
            is_fully_buildable=r.is_fully_buildable,
            missing_count=r.missing_count,
        )
        for r in ranked
    ]


@router.get("/decks/status", response_model=PreconSyncStatusRead)
def get_sync_status(db: Session = Depends(get_db)) -> PreconSyncStatusRead:
    return PreconSyncStatusRead.model_validate(precon_service.get_sync_state(db))


@router.post("/decks/sync", response_model=PreconSyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> PreconSyncStatusRead:
    try:
        state = precon_service.trigger_sync(db)
    except precon_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a precon sync is already in progress") from exc
    return PreconSyncStatusRead.model_validate(state)
