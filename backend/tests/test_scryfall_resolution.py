from __future__ import annotations

from app.core.database import get_sessionmaker
from app.models.collection import Collection, CollectionItem
from app.models.scryfall import ScryfallCard
from app.models.user import DEFAULT_USER_ID
from app.services import scryfall_resolution


def _make_card(**overrides: object) -> ScryfallCard:
    defaults: dict[str, object] = {
        "id": "e3285e6b-3e79-4d7c-bf96-d920f973b122",
        "oracle_id": "4457ed35-7c10-48c8-9776-456485fdf070",
        "name": "Lightning Bolt",
        "set_code": "LEA",
        "set_name": "Limited Edition Alpha",
        "collector_number": "161",
        "lang": "en",
        "layout": "normal",
    }
    defaults.update(overrides)
    return ScryfallCard(**defaults)  # type: ignore[arg-type]


def _make_collection(db) -> Collection:
    collection = Collection(user_id=DEFAULT_USER_ID, name="Test", is_default=True)
    db.add(collection)
    db.flush()
    return collection


def _make_item(db, collection: Collection, **overrides: object) -> CollectionItem:
    defaults: dict[str, object] = {
        "collection_id": collection.id,
        "card_name": "Lightning Bolt",
        "quantity": 1,
    }
    defaults.update(overrides)
    item = CollectionItem(**defaults)  # type: ignore[arg-type]
    db.add(item)
    db.flush()
    return item


def test_resolves_by_scryfall_id():
    db = get_sessionmaker()()
    try:
        card = _make_card()
        db.add(card)
        collection = _make_collection(db)
        item = _make_item(db, collection, scryfall_id=card.id)

        scryfall_resolution.resolve_item(db, item)

        assert item.resolved_scryfall_card_id == card.id
        assert item.resolved_oracle_id == card.oracle_id
        assert item.resolved_at is not None
    finally:
        db.rollback()
        db.close()


def test_resolves_by_set_and_collector_number():
    db = get_sessionmaker()()
    try:
        card = _make_card()
        db.add(card)
        collection = _make_collection(db)
        item = _make_item(db, collection, set_code="lea", collector_number="161")

        scryfall_resolution.resolve_item(db, item)

        assert item.resolved_scryfall_card_id == card.id
        assert item.resolved_oracle_id == card.oracle_id
    finally:
        db.rollback()
        db.close()


def test_set_and_number_match_prefers_item_language():
    db = get_sessionmaker()()
    try:
        en_card = _make_card(id="11111111-1111-1111-1111-111111111111", lang="en")
        de_card = _make_card(id="22222222-2222-2222-2222-222222222222", lang="de")
        db.add_all([en_card, de_card])
        collection = _make_collection(db)
        item = _make_item(db, collection, set_code="LEA", collector_number="161", language="DE")

        scryfall_resolution.resolve_item(db, item)

        assert item.resolved_scryfall_card_id == de_card.id
    finally:
        db.rollback()
        db.close()


def test_falls_back_to_name_only_match_when_no_set_info():
    db = get_sessionmaker()()
    try:
        card = _make_card()
        db.add(card)
        collection = _make_collection(db)
        item = _make_item(db, collection, card_name="lightning bolt")  # case-insensitive

        scryfall_resolution.resolve_item(db, item)

        assert item.resolved_oracle_id == card.oracle_id
        assert item.resolved_scryfall_card_id is None  # no specific printing determinable
    finally:
        db.rollback()
        db.close()


def test_no_match_leaves_both_fields_null():
    db = get_sessionmaker()()
    try:
        collection = _make_collection(db)
        item = _make_item(db, collection, card_name="Not A Real Card Name XYZ")

        scryfall_resolution.resolve_item(db, item)

        assert item.resolved_oracle_id is None
        assert item.resolved_scryfall_card_id is None
        assert item.resolved_at is not None  # attempted, just unsuccessfully
    finally:
        db.rollback()
        db.close()


def test_resolve_collection_summary_counts():
    db = get_sessionmaker()()
    try:
        card = _make_card()
        db.add(card)
        collection = _make_collection(db)
        _make_item(db, collection, scryfall_id=card.id)  # resolved_exact
        _make_item(db, collection, card_name="lightning bolt")  # resolved_oracle_only
        _make_item(db, collection, card_name="Totally Unknown Card")  # unresolved
        db.commit()

        summary = scryfall_resolution.resolve_collection(db, collection.id)

        assert summary.total == 3
        assert summary.resolved_exact == 1
        assert summary.resolved_oracle_only == 1
        assert summary.unresolved == 1
    finally:
        db.close()
