from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.database import get_sessionmaker
from app.models.collection import Collection, CollectionItem
from app.models.discover import PopularDeck
from app.models.pricing import PriceObservation, PriceProvider
from app.models.scryfall import ScryfallCard
from app.models.user import DEFAULT_USER_ID
from app.parsers.common import ParsedRow, ParseResult
from app.services import discover_service, pricing_service
from app.source_adapters import moxfield
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.errors import SourceFetchError

SOL_RING_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SOL_RING_ORACLE = "aaaaaaaa-0000-0000-0000-0000000000a1"
MANA_CRYPT_ID = "bbbbbbbb-0000-0000-0000-000000000002"
MANA_CRYPT_ORACLE = "bbbbbbbb-0000-0000-0000-0000000000b1"


def _row(name: str, quantity: int) -> ParsedRow:
    return ParsedRow(
        row_number=1,
        raw={"name": name},
        mapped={
            "name": name,
            "quantity": quantity,
            "set_code": None,
            "collector_number": None,
            "language": None,
            "scryfall_id": None,
        },
    )


def _seed_cards(db) -> None:
    db.add(
        ScryfallCard(
            id=SOL_RING_ID, oracle_id=SOL_RING_ORACLE, name="Sol Ring", set_code="C21", set_name="Commander 2021",
            collector_number="263", lang="en", layout="normal",
        )
    )
    db.add(
        ScryfallCard(
            id=MANA_CRYPT_ID, oracle_id=MANA_CRYPT_ORACLE, name="Mana Crypt", set_code="2X2",
            set_name="Double Masters 2022", collector_number="209", lang="en", layout="normal",
        )
    )
    db.commit()


def _seed_price(db, scryfall_card_id: str, price: str) -> None:
    db.add(
        PriceObservation(
            scryfall_card_id=scryfall_card_id, provider=PriceProvider.manual.value, currency="USD", foil=False,
            price=Decimal(price),
        )
    )
    db.commit()


def _seed_deck(db, **overrides: object) -> PopularDeck:
    defaults: dict[str, object] = {
        "source": "moxfield",
        "external_id": "mox-1",
        "name": "Test Deck",
        "author": "Alice",
        "source_url": "https://moxfield.example/decks/mox-1",
        "format": "commander",
        "view_count": 100,
        "like_count": 10,
        "color_identity": ["W"],
    }
    defaults.update(overrides)
    deck = PopularDeck(**defaults)
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


def _seed_collection(db, items: list[tuple[str, str, int]]) -> Collection:
    collection = Collection(user_id=DEFAULT_USER_ID, name="Test", is_default=True)
    db.add(collection)
    db.flush()
    for name, oracle_id, qty in items:
        db.add(CollectionItem(collection_id=collection.id, card_name=name, quantity=qty, resolved_oracle_id=oracle_id))
    db.commit()
    return collection


def test_price_popular_deck_caches_full_price(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        _seed_cards(db)
        _seed_price(db, SOL_RING_ID, "2.00")
        _seed_price(db, MANA_CRYPT_ID, "150.00")
        collection = _seed_collection(db, [])
        deck = _seed_deck(db)
        profile = pricing_service.get_or_create_default_price_profile(db)

        parse_result = ParseResult(rows=[_row("Sol Ring", 1), _row("Mana Crypt", 1)])
        monkeypatch.setattr(
            moxfield, "fetch_and_parse", lambda url, user_agent: DeckFetchResult(deck_name="Test Deck", parse_result=parse_result)
        )

        priced = discover_service.price_popular_deck(
            db, deck.id, collection_id=collection.id, price_profile_id=profile.id, user_agent="test-agent"
        )

        assert priced.coverage_percent == 0.0
        assert priced.missing_cost == Decimal("152.00")
        assert priced.missing_cost_currency == "USD"
        assert priced.unpriced_missing_count == 0
        assert priced.priced_at is not None
    finally:
        db.close()


def test_price_popular_deck_reports_unpriced_cards(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        _seed_cards(db)
        _seed_price(db, SOL_RING_ID, "2.00")
        # Mana Crypt has no price observation at all.
        collection = _seed_collection(db, [])
        deck = _seed_deck(db)
        profile = pricing_service.get_or_create_default_price_profile(db)

        parse_result = ParseResult(rows=[_row("Sol Ring", 1), _row("Mana Crypt", 1)])
        monkeypatch.setattr(
            moxfield, "fetch_and_parse", lambda url, user_agent: DeckFetchResult(deck_name="Test Deck", parse_result=parse_result)
        )

        priced = discover_service.price_popular_deck(
            db, deck.id, collection_id=collection.id, price_profile_id=profile.id, user_agent="test-agent"
        )

        assert priced.missing_cost == Decimal("2.00")
        assert priced.unpriced_missing_count == 1
    finally:
        db.close()


def test_price_popular_deck_fully_owned_is_zero_cost(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        _seed_cards(db)
        collection = _seed_collection(db, [("Sol Ring", SOL_RING_ORACLE, 1)])
        deck = _seed_deck(db)
        profile = pricing_service.get_or_create_default_price_profile(db)

        parse_result = ParseResult(rows=[_row("Sol Ring", 1)])
        monkeypatch.setattr(
            moxfield, "fetch_and_parse", lambda url, user_agent: DeckFetchResult(deck_name="Test Deck", parse_result=parse_result)
        )

        priced = discover_service.price_popular_deck(
            db, deck.id, collection_id=collection.id, price_profile_id=profile.id, user_agent="test-agent"
        )

        assert priced.coverage_percent == 100.0
        assert priced.missing_cost == Decimal("0")
        assert priced.unpriced_missing_count == 0
    finally:
        db.close()


def test_price_popular_deck_raises_for_missing_deck():
    db = get_sessionmaker()()
    try:
        profile = pricing_service.get_or_create_default_price_profile(db)
        with pytest.raises(discover_service.DeckNotFoundError):
            discover_service.price_popular_deck(
                db, 999999, collection_id=1, price_profile_id=profile.id, user_agent="test-agent"
            )
    finally:
        db.close()


def test_price_popular_deck_raises_for_missing_price_profile():
    db = get_sessionmaker()()
    try:
        collection = _seed_collection(db, [])
        deck = _seed_deck(db)
        with pytest.raises(pricing_service.PriceProfileNotFoundError):
            discover_service.price_popular_deck(
                db, deck.id, collection_id=collection.id, price_profile_id=999999, user_agent="test-agent"
            )
    finally:
        db.close()


def test_price_popular_deck_propagates_fetch_failure(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        collection = _seed_collection(db, [])
        deck = _seed_deck(db)
        profile = pricing_service.get_or_create_default_price_profile(db)

        def _boom(url: str, user_agent: str) -> DeckFetchResult:
            raise SourceFetchError("moxfield unreachable")

        monkeypatch.setattr(moxfield, "fetch_and_parse", _boom)

        with pytest.raises(SourceFetchError):
            discover_service.price_popular_deck(
                db, deck.id, collection_id=collection.id, price_profile_id=profile.id, user_agent="test-agent"
            )
    finally:
        db.close()
