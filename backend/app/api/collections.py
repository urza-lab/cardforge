from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.collection import CollectionCreate, CollectionItemRead, CollectionRead, ResolutionSummaryRead
from app.services import collection_service, scryfall_resolution

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.get("", response_model=list[CollectionRead])
def list_collections(db: Session = Depends(get_db)) -> list[CollectionRead]:
    return [CollectionRead.model_validate(c) for c in collection_service.list_collections(db)]


@router.post("", response_model=CollectionRead, status_code=201)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)) -> CollectionRead:
    return CollectionRead.model_validate(collection_service.create_collection(db, name=payload.name))


@router.get("/default", response_model=CollectionRead)
def get_default_collection(db: Session = Depends(get_db)) -> CollectionRead:
    """Returns (creating on first call) the single collection a single-user
    setup can treat as "the" collection — see ARCHITECTURE.md auth model
    default decision. Must be declared before /{collection_id} below so
    "default" isn't swallowed by that path param.
    """
    return CollectionRead.model_validate(collection_service.get_or_create_default_collection(db))


@router.get("/{collection_id}", response_model=CollectionRead)
def get_collection(collection_id: int, db: Session = Depends(get_db)) -> CollectionRead:
    collection = collection_service.get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")
    return CollectionRead.model_validate(collection)


@router.get("/{collection_id}/items", response_model=list[CollectionItemRead])
def list_collection_items(collection_id: int, db: Session = Depends(get_db)) -> list[CollectionItemRead]:
    collection = collection_service.get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")
    return [CollectionItemRead.model_validate(i) for i in collection_service.list_items(db, collection_id)]


@router.post("/{collection_id}/resolve", response_model=ResolutionSummaryRead)
def resolve_collection(collection_id: int, db: Session = Depends(get_db)) -> ResolutionSummaryRead:
    """Re-match every item in this collection against the local Scryfall
    mirror. Items are already resolved once at import time (Phase 2's
    confirm_import calls this per-item); this is for re-running it in bulk
    after a Scryfall sync fills in data that wasn't there yet.
    """
    collection = collection_service.get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")
    summary = scryfall_resolution.resolve_collection(db, collection_id)
    return ResolutionSummaryRead(
        total=summary.total,
        resolved_exact=summary.resolved_exact,
        resolved_oracle_only=summary.resolved_oracle_only,
        unresolved=summary.unresolved,
    )
