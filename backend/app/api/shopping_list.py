from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.lists import ListComparisonResponse
from app.services import collection_service, comparison_service, list_service, pricing_service

router = APIRouter(prefix="/api/shopping-list", tags=["shopping-list"])


@router.get("", response_model=ListComparisonResponse)
def get_shopping_list(
    list_ids: str,
    collection_id: int | None = None,
    mode: str = "oracle",
    price_profile_id: int | None = None,
    budget: Decimal | None = None,
    db: Session = Depends(get_db),
) -> ListComparisonResponse:
    """Missing cards across several lists at once, compared against one
    shared owned pool (see comparison_service.run_shopping_list for why that
    matters). `list_ids` is a comma-separated list of CardList ids. Pricing
    is opt-in via price_profile_id - see schemas.lists.ListComparisonResponse.
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

    try:
        priced_missing, budget_result = pricing_service.price_and_budget_missing_cards(
            db, result.missing, result.mode, price_profile_id=price_profile_id, budget=budget
        )
    except pricing_service.PriceProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="price profile not found") from exc

    return ListComparisonResponse.from_result(result, priced_missing, budget_result)
