from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.comparison import MissingCardRead
from app.schemas.lists import ListComparisonResponse
from app.services import collection_service, comparison_service, list_service

router = APIRouter(prefix="/api/shopping-list", tags=["shopping-list"])


@router.get("", response_model=ListComparisonResponse)
def get_shopping_list(
    list_ids: str, collection_id: int | None = None, mode: str = "oracle", db: Session = Depends(get_db)
) -> ListComparisonResponse:
    """Missing cards across several lists at once, compared against one
    shared owned pool (see comparison_service.run_shopping_list for why that
    matters). `list_ids` is a comma-separated list of CardList ids.
    """
    try:
        ids = [int(x) for x in list_ids.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="list_ids must be a comma-separated list of integers"
        ) from exc
    if not ids:
        raise HTTPException(status_code=400, detail="list_ids must not be empty")

    for list_id in ids:
        if list_service.get_list(db, list_id) is None:
            raise HTTPException(status_code=404, detail=f"list {list_id} not found")

    if collection_id is None:
        collection_id = collection_service.get_or_create_default_collection(db).id
    elif collection_service.get_collection(db, collection_id) is None:
        raise HTTPException(status_code=404, detail="collection not found")

    try:
        result = comparison_service.run_shopping_list(
            db, list_ids=ids, collection_id=collection_id, mode=mode
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
