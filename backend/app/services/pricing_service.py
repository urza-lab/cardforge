"""Price profile CRUD, manual price entry, and price resolution (Phase 6).
See PRICING.md. Kept separate from mtgjson_service.py (that one's just the
sync-trigger orchestration, mirroring scryfall_service.py) since this module
has nothing to do with any particular provider's sync job.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comparison.types import MissingCard
from app.models.pricing import (
    DEFAULT_PRICE_PROFILE_NAME,
    DEFAULT_PROVIDER_PRIORITY,
    PriceObservation,
    PriceProfile,
    PriceProvider,
)
from app.models.scryfall import ScryfallCard
from app.models.user import DEFAULT_USER_ID
from app.pricing.budget import BudgetResult, PricedMissingCard, apply_budget

VALID_PROVIDERS = {p.value for p in PriceProvider}


class InvalidProviderPriorityError(ValueError):
    pass


class PriceProfileNotFoundError(Exception):
    pass


class CardNotFoundError(Exception):
    pass


def _validate_provider_priority(provider_priority: list[str]) -> None:
    unknown = set(provider_priority) - VALID_PROVIDERS
    if unknown:
        raise InvalidProviderPriorityError(
            f"unknown provider(s) {sorted(unknown)}, expected a subset of {sorted(VALID_PROVIDERS)}"
        )
    if not provider_priority:
        raise InvalidProviderPriorityError("provider_priority must not be empty")


def list_price_profiles(db: Session, user_id: int = DEFAULT_USER_ID) -> list[PriceProfile]:
    stmt = select(PriceProfile).where(PriceProfile.user_id == user_id).order_by(PriceProfile.created_at)
    return list(db.scalars(stmt))


def get_price_profile(db: Session, profile_id: int, user_id: int = DEFAULT_USER_ID) -> PriceProfile | None:
    stmt = select(PriceProfile).where(PriceProfile.id == profile_id, PriceProfile.user_id == user_id)
    return db.scalars(stmt).first()


def get_or_create_default_price_profile(db: Session, user_id: int = DEFAULT_USER_ID) -> PriceProfile:
    stmt = select(PriceProfile).where(PriceProfile.user_id == user_id, PriceProfile.is_default.is_(True))
    existing = db.scalars(stmt).first()
    if existing is not None:
        return existing
    return create_price_profile(
        db,
        name=DEFAULT_PRICE_PROFILE_NAME,
        currency="USD",
        provider_priority=list(DEFAULT_PROVIDER_PRIORITY),
        prefer_foil=False,
        is_default=True,
        user_id=user_id,
    )


def create_price_profile(
    db: Session,
    *,
    name: str,
    currency: str,
    provider_priority: list[str],
    prefer_foil: bool = False,
    is_default: bool = False,
    user_id: int = DEFAULT_USER_ID,
) -> PriceProfile:
    _validate_provider_priority(provider_priority)
    if is_default:
        _clear_existing_default(db, user_id)
    profile = PriceProfile(
        user_id=user_id,
        name=name,
        currency=currency.upper(),
        provider_priority=provider_priority,
        prefer_foil=prefer_foil,
        is_default=is_default,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_price_profile(
    db: Session,
    profile: PriceProfile,
    *,
    name: str | None = None,
    currency: str | None = None,
    provider_priority: list[str] | None = None,
    prefer_foil: bool | None = None,
    is_default: bool | None = None,
) -> PriceProfile:
    if provider_priority is not None:
        _validate_provider_priority(provider_priority)
        profile.provider_priority = provider_priority
    if name is not None:
        profile.name = name
    if currency is not None:
        profile.currency = currency.upper()
    if prefer_foil is not None:
        profile.prefer_foil = prefer_foil
    if is_default is True and not profile.is_default:
        _clear_existing_default(db, profile.user_id)
        profile.is_default = True
    elif is_default is False:
        profile.is_default = False
    db.commit()
    db.refresh(profile)
    return profile


def _clear_existing_default(db: Session, user_id: int) -> None:
    stmt = select(PriceProfile).where(PriceProfile.user_id == user_id, PriceProfile.is_default.is_(True))
    for existing in db.scalars(stmt):
        existing.is_default = False


def delete_price_profile(db: Session, profile: PriceProfile) -> None:
    # No "can't delete the last/default profile" guard - get_or_create_
    # default_price_profile transparently creates a fresh one the next time
    # anything needs one, same as collections' default-bootstrap pattern.
    db.delete(profile)
    db.commit()


def resolve_price(db: Session, scryfall_card_id: str, profile: PriceProfile) -> tuple[Decimal | None, str | None]:
    """Walks profile.provider_priority in order, returns the first match's
    (price, provider) - or (None, None) if no provider in the profile has a
    price for this card/currency/foil combination. Never invents a price.
    """
    for provider in profile.provider_priority:
        stmt = select(PriceObservation).where(
            PriceObservation.scryfall_card_id == scryfall_card_id,
            PriceObservation.provider == provider,
            PriceObservation.currency == profile.currency,
            PriceObservation.foil == profile.prefer_foil,
        )
        obs = db.scalars(stmt).first()
        if obs is not None:
            return obs.price, obs.provider
    return None, None


def set_manual_price(
    db: Session, *, scryfall_card_id: str, currency: str, foil: bool, price: Decimal
) -> PriceObservation:
    if db.get(ScryfallCard, scryfall_card_id) is None:
        raise CardNotFoundError(scryfall_card_id)

    stmt = select(PriceObservation).where(
        PriceObservation.scryfall_card_id == scryfall_card_id,
        PriceObservation.provider == PriceProvider.manual.value,
        PriceObservation.currency == currency,
        PriceObservation.foil == foil,
    )
    existing = db.scalars(stmt).first()
    if existing is not None:
        existing.price = price
        db.commit()
        db.refresh(existing)
        return existing

    observation = PriceObservation(
        scryfall_card_id=scryfall_card_id,
        provider=PriceProvider.manual.value,
        currency=currency.upper(),
        foil=foil,
        price=price,
    )
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


def clear_manual_price(db: Session, *, scryfall_card_id: str, currency: str, foil: bool) -> bool:
    stmt = select(PriceObservation).where(
        PriceObservation.scryfall_card_id == scryfall_card_id,
        PriceObservation.provider == PriceProvider.manual.value,
        PriceObservation.currency == currency,
        PriceObservation.foil == foil,
    )
    existing = db.scalars(stmt).first()
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def get_card_prices(db: Session, scryfall_card_id: str) -> list[PriceObservation]:
    stmt = select(PriceObservation).where(PriceObservation.scryfall_card_id == scryfall_card_id)
    return list(db.scalars(stmt))


def resolve_cheapest_price_for_oracle(
    db: Session, oracle_id: str, profile: PriceProfile
) -> tuple[Decimal | None, str | None]:
    """"Any printing satisfies this" is oracle-mode comparison's own
    philosophy - see app.comparison.engine) extends naturally to pricing: the
    realistic cost of closing an oracle-mode gap is whatever the *cheapest*
    printing of that card costs, not whichever printing a particular import
    happened to resolve to. Checks every printing sharing the oracle_id
    against the profile's provider priority and keeps the lowest match.

    Not batched (one resolve_price call, and one provider-priority walk,
    per candidate printing) - fine for a self-hosted single-user tool's
    dozens-of-missing-cards-times-single-digit-printings-each scale; would
    need a real batched query if this ever ran over hundreds of oracle
    groups per request.
    """
    candidate_ids = [row[0] for row in db.execute(select(ScryfallCard.id).where(ScryfallCard.oracle_id == oracle_id))]
    best_price: Decimal | None = None
    best_provider: str | None = None
    for candidate_id in candidate_ids:
        price, provider = resolve_price(db, candidate_id, profile)
        if price is not None and (best_price is None or price < best_price):
            best_price, best_provider = price, provider
    return best_price, best_provider


def resolve_price_for_missing_card(
    db: Session, missing: MissingCard, profile: PriceProfile, mode: str
) -> tuple[Decimal | None, str | None]:
    if mode == "printing" and missing.scryfall_card_id:
        return resolve_price(db, missing.scryfall_card_id, profile)
    if missing.oracle_id:
        return resolve_cheapest_price_for_oracle(db, missing.oracle_id, profile)
    if missing.scryfall_card_id:
        return resolve_price(db, missing.scryfall_card_id, profile)
    return None, None


def price_missing_cards(
    db: Session, missing: list[MissingCard], profile: PriceProfile, mode: str
) -> list[PricedMissingCard]:
    priced: list[PricedMissingCard] = []
    for card in missing:
        price, provider = resolve_price_for_missing_card(db, card, profile, mode)
        priced.append(
            PricedMissingCard(
                name=card.name,
                oracle_id=card.oracle_id,
                missing_quantity=card.missing_quantity,
                unit_price=price,
                provider=provider,
            )
        )
    return priced


def price_and_budget_missing_cards(
    db: Session,
    missing: list[MissingCard],
    mode: str,
    *,
    price_profile_id: int | None,
    budget: Decimal | None,
) -> tuple[list[PricedMissingCard] | None, BudgetResult | None]:
    """Shared by the per-list comparison and shopping-list API endpoints -
    pricing is opt-in (see schemas.lists.ListComparisonResponse) so this
    returns (None, None) unless a price_profile_id was actually given.
    """
    if price_profile_id is None:
        return None, None
    profile = get_price_profile(db, price_profile_id)
    if profile is None:
        raise PriceProfileNotFoundError(price_profile_id)

    priced = price_missing_cards(db, missing, profile, mode)
    budget_result = apply_budget(priced, budget, profile.currency) if budget is not None else None
    return priced, budget_result
