from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.pricing import PriceProfile
from app.schemas.pricing import (
    CardPriceRead,
    ManualPriceSetRequest,
    PriceObservationRead,
    PriceProfileCreate,
    PriceProfileRead,
    PriceProfileUpdate,
)
from app.services import pricing_service

router = APIRouter(tags=["prices"])


@router.get("/api/price-profiles", response_model=list[PriceProfileRead])
def list_price_profiles(db: Session = Depends(get_db)) -> list[PriceProfileRead]:
    return [PriceProfileRead.model_validate(p) for p in pricing_service.list_price_profiles(db)]


@router.get("/api/price-profiles/default", response_model=PriceProfileRead)
def get_default_price_profile(db: Session = Depends(get_db)) -> PriceProfileRead:
    return PriceProfileRead.model_validate(pricing_service.get_or_create_default_price_profile(db))


@router.post("/api/price-profiles", response_model=PriceProfileRead, status_code=201)
def create_price_profile(payload: PriceProfileCreate, db: Session = Depends(get_db)) -> PriceProfileRead:
    try:
        profile = pricing_service.create_price_profile(
            db,
            name=payload.name,
            currency=payload.currency,
            provider_priority=payload.provider_priority,
            prefer_foil=payload.prefer_foil,
        )
    except pricing_service.InvalidProviderPriorityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PriceProfileRead.model_validate(profile)


@router.get("/api/price-profiles/{profile_id}", response_model=PriceProfileRead)
def get_price_profile(profile_id: int, db: Session = Depends(get_db)) -> PriceProfileRead:
    profile = pricing_service.get_price_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="price profile not found")
    return PriceProfileRead.model_validate(profile)


@router.put("/api/price-profiles/{profile_id}", response_model=PriceProfileRead)
def update_price_profile(
    profile_id: int, payload: PriceProfileUpdate, db: Session = Depends(get_db)
) -> PriceProfileRead:
    profile = pricing_service.get_price_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="price profile not found")
    try:
        updated = pricing_service.update_price_profile(
            db,
            profile,
            name=payload.name,
            currency=payload.currency,
            provider_priority=payload.provider_priority,
            prefer_foil=payload.prefer_foil,
            is_default=payload.is_default,
        )
    except pricing_service.InvalidProviderPriorityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PriceProfileRead.model_validate(updated)


@router.delete("/api/price-profiles/{profile_id}", status_code=204, response_model=None)
def delete_price_profile(profile_id: int, db: Session = Depends(get_db)) -> None:
    profile = pricing_service.get_price_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="price profile not found")
    pricing_service.delete_price_profile(db, profile)


@router.get("/api/prices/{scryfall_card_id}", response_model=list[PriceObservationRead])
def get_card_prices(scryfall_card_id: str, db: Session = Depends(get_db)) -> list[PriceObservationRead]:
    return [PriceObservationRead.model_validate(o) for o in pricing_service.get_card_prices(db, scryfall_card_id)]


@router.get("/api/prices/{scryfall_card_id}/resolve", response_model=CardPriceRead)
def resolve_card_price(
    scryfall_card_id: str, profile_id: int | None = Query(default=None), db: Session = Depends(get_db)
) -> CardPriceRead:
    profile: PriceProfile | None
    if profile_id is None:
        profile = pricing_service.get_or_create_default_price_profile(db)
    else:
        profile = pricing_service.get_price_profile(db, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="price profile not found")

    price, provider = pricing_service.resolve_price(db, scryfall_card_id, profile)
    return CardPriceRead(
        scryfall_card_id=scryfall_card_id,
        currency=profile.currency,
        foil=profile.prefer_foil,
        price=price,
        provider=provider,
    )


@router.post("/api/prices/manual", response_model=PriceObservationRead, status_code=201)
def set_manual_price(payload: ManualPriceSetRequest, db: Session = Depends(get_db)) -> PriceObservationRead:
    try:
        observation = pricing_service.set_manual_price(
            db,
            scryfall_card_id=payload.scryfall_card_id,
            currency=payload.currency,
            foil=payload.foil,
            price=payload.price,
        )
    except pricing_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"scryfall card '{exc}' not found in the local mirror") from exc
    return PriceObservationRead.model_validate(observation)


@router.delete("/api/prices/manual", status_code=204, response_model=None)
def clear_manual_price(
    scryfall_card_id: str, currency: str, foil: bool = False, db: Session = Depends(get_db)
) -> None:
    pricing_service.clear_manual_price(db, scryfall_card_id=scryfall_card_id, currency=currency, foil=foil)
