from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.comparison import MissingCardRead
from app.schemas.lists import CardListCreate, CardListItemRead, CardListRead, ListComparisonResponse
from app.models.lists import CardList
from app.services import (
    collection_service,
    comparison_service,
    display_name_service,
    export_service,
    list_refresh_service,
    list_service,
    settings_service,
)

router = APIRouter(prefix="/api/lists", tags=["lists"])


def _to_read(card_list: CardList) -> CardListRead:
    return CardListRead.model_validate(card_list).model_copy(
        update={"is_stale": list_refresh_service.is_stale(card_list)}
    )


@router.get("", response_model=list[CardListRead])
def list_all(db: Session = Depends(get_db)) -> list[CardListRead]:
    return [_to_read(item) for item in list_service.list_lists(db)]


@router.post("", response_model=CardListRead, status_code=201)
def create_list(payload: CardListCreate, db: Session = Depends(get_db)) -> CardListRead:
    try:
        card_list = list_service.create_list(db, name=payload.name, list_type=payload.list_type)
    except list_service.InvalidListTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_read(card_list)


@router.get("/{list_id}", response_model=CardListRead)
def get_list(list_id: int, db: Session = Depends(get_db)) -> CardListRead:
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")
    return _to_read(card_list)


@router.post("/{list_id}/refresh", response_model=CardListRead, status_code=202)
def refresh_list(list_id: int, db: Session = Depends(get_db)) -> CardListRead:
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")
    try:
        card_list = list_refresh_service.trigger_refresh(db, card_list)
    except list_refresh_service.NotUrlSourcedError as exc:
        raise HTTPException(
            status_code=400, detail="list has no source URL to refresh from (it wasn't imported from one)"
        ) from exc
    except list_refresh_service.RefreshAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a refresh for this list is already in progress") from exc
    return _to_read(card_list)


@router.delete("/{list_id}", status_code=204, response_model=None)
def delete_list(list_id: int, db: Session = Depends(get_db)) -> None:
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")
    list_service.delete_list(db, card_list)


@router.get("/{list_id}/items", response_model=list[CardListItemRead])
def list_items(list_id: int, db: Session = Depends(get_db)) -> list[CardListItemRead]:
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")
    items = list_service.list_items(db, list_id)
    override = settings_service.get_settings(db).card_name_language
    display_names = display_name_service.get_display_names(db, items, override_language=override)
    return [
        CardListItemRead.model_validate(item).model_copy(update={"display_name": display_names[item.id]})
        for item in items
    ]


@router.get("/{list_id}/export.csv")
def export_list_csv(list_id: int, db: Session = Depends(get_db)) -> Response:
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")
    csv_text = export_service.list_items_to_csv(list_service.list_items(db, list_id))
    filename = f"{card_list.name}.csv".replace('"', "")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{list_id}/comparison", response_model=ListComparisonResponse)
def compare_list(
    list_id: int, collection_id: int | None = None, mode: str = "oracle", db: Session = Depends(get_db)
) -> ListComparisonResponse:
    """Buildability of this list's mainboard/commander/companion cards
    against a collection (default: the single-user default collection, see
    ARCHITECTURE.md) — reuses the Phase 3 comparison engine, nothing new to
    compute here besides picking which items count as "required".
    """
    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")

    if collection_id is None:
        collection_id = collection_service.get_or_create_default_collection(db).id
    elif collection_service.get_collection(db, collection_id) is None:
        raise HTTPException(status_code=404, detail="collection not found")

    try:
        result = comparison_service.run_list_comparison(
            db, list_id=list_id, collection_id=collection_id, mode=mode
        )
    except comparison_service.InvalidComparisonModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ListComparisonResponse(
        mode=result.mode,
        total_required_cards=result.total_required_cards,
        total_required_quantity=result.total_required_quantity,
        total_owned_quantity=result.total_owned_quantity,
        coverage_percent=result.coverage_percent,
        is_fully_buildable=result.is_fully_buildable,
        missing=[
            MissingCardRead(
                name=m.name,
                oracle_id=m.oracle_id,
                required_quantity=m.required_quantity,
                owned_quantity=m.owned_quantity,
                missing_quantity=m.missing_quantity,
            )
            for m in result.missing
        ],
    )
