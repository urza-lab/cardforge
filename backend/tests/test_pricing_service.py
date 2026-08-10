from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.database import get_sessionmaker
from app.models.pricing import PriceObservation, PriceProvider
from app.models.scryfall import ScryfallCard
from app.services import pricing_service

BOLT_ID = "e3285e6b-3e79-4d7c-bf96-d920f973b122"


@pytest.fixture
def db():
    session = get_sessionmaker()()
    session.add(
        ScryfallCard(
            id=BOLT_ID, oracle_id="4457ed35-7c10-48c8-9776-456485fdf070", name="Lightning Bolt",
            set_code="LEA", set_name="Limited Edition Alpha", collector_number="161", lang="en", layout="normal",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_get_or_create_default_price_profile_is_idempotent(db):
    first = pricing_service.get_or_create_default_price_profile(db)
    second = pricing_service.get_or_create_default_price_profile(db)
    assert first.id == second.id
    assert first.is_default is True
    assert first.provider_priority == ["manual", "mtgjson", "scryfall"]


def test_create_price_profile_rejects_unknown_provider(db):
    with pytest.raises(pricing_service.InvalidProviderPriorityError):
        pricing_service.create_price_profile(db, name="Bad", currency="USD", provider_priority=["ebay"])


def test_setting_a_second_default_unsets_the_first(db):
    first = pricing_service.get_or_create_default_price_profile(db)
    second = pricing_service.create_price_profile(
        db, name="Budget EUR", currency="EUR", provider_priority=["mtgjson"], is_default=True
    )
    db.refresh(first)
    assert first.is_default is False
    assert second.is_default is True


def test_set_and_resolve_manual_price(db):
    pricing_service.set_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False, price=Decimal("1.23"))
    profile = pricing_service.get_or_create_default_price_profile(db)

    price, provider = pricing_service.resolve_price(db, BOLT_ID, profile)
    assert price == Decimal("1.23")
    assert provider == "manual"


def test_set_manual_price_upserts_not_duplicates(db):
    pricing_service.set_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False, price=Decimal("1.00"))
    pricing_service.set_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False, price=Decimal("2.00"))

    rows = db.query(PriceObservation).filter(
        PriceObservation.scryfall_card_id == BOLT_ID, PriceObservation.provider == "manual"
    ).all()
    assert len(rows) == 1
    assert rows[0].price == Decimal("2.00")


def test_set_manual_price_unknown_card_raises(db):
    with pytest.raises(pricing_service.CardNotFoundError):
        pricing_service.set_manual_price(
            db, scryfall_card_id="00000000-0000-0000-0000-000000000000", currency="USD", foil=False,
            price=Decimal("1.00"),
        )


def test_clear_manual_price(db):
    pricing_service.set_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False, price=Decimal("1.00"))
    cleared = pricing_service.clear_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False)
    assert cleared is True
    assert db.query(PriceObservation).count() == 0
    assert pricing_service.clear_manual_price(db, scryfall_card_id=BOLT_ID, currency="USD", foil=False) is False


def test_resolve_price_falls_through_provider_priority(db):
    db.add(
        PriceObservation(
            scryfall_card_id=BOLT_ID, provider=PriceProvider.scryfall.value, currency="USD", foil=False,
            price=Decimal("5.00"),
        )
    )
    db.commit()
    profile = pricing_service.get_or_create_default_price_profile(db)  # manual, mtgjson, scryfall

    price, provider = pricing_service.resolve_price(db, BOLT_ID, profile)
    assert price == Decimal("5.00")
    assert provider == "scryfall"


def test_resolve_price_no_match_returns_none(db):
    profile = pricing_service.get_or_create_default_price_profile(db)
    price, provider = pricing_service.resolve_price(db, BOLT_ID, profile)
    assert price is None
    assert provider is None
