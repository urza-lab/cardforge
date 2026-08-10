from __future__ import annotations

from app.core.database import get_sessionmaker
from app.models.collection import Collection, CollectionItem
from app.models.scryfall import ScryfallCard
from app.models.user import DEFAULT_USER_ID
from app.services import display_name_service


def _seed_card(db, **overrides: object) -> ScryfallCard:
    defaults: dict[str, object] = {
        "id": "e3285e6b-3e79-4d7c-bf96-d920f973b122",
        "oracle_id": "4457ed35-7c10-48c8-9776-456485fdf070",
        "name": "Lightning Bolt",
        "printed_name": None,
        "set_code": "LEA",
        "set_name": "Limited Edition Alpha",
        "collector_number": "161",
        "lang": "en",
        "layout": "normal",
    }
    defaults.update(overrides)
    card = ScryfallCard(**defaults)  # type: ignore[arg-type]
    db.add(card)
    return card


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


def test_defaults_to_english_when_item_language_is_english():
    db = get_sessionmaker()()
    try:
        collection = _make_collection(db)
        item = _make_item(db, collection, language="EN", resolved_oracle_id="oracle-1")
        names = display_name_service.get_display_names(db, [item])
        assert names[item.id] == "Lightning Bolt"
    finally:
        db.rollback()
        db.close()


def test_uses_printed_name_for_items_own_language():
    db = get_sessionmaker()()
    try:
        card = _seed_card(
            db,
            id="11111111-1111-1111-1111-111111111111",
            lang="de",
            printed_name="Blitzschlag",
        )
        collection = _make_collection(db)
        item = _make_item(db, collection, language="DE", resolved_oracle_id=card.oracle_id)
        names = display_name_service.get_display_names(db, [item])
        assert names[item.id] == "Blitzschlag"
    finally:
        db.rollback()
        db.close()


def test_falls_back_to_english_when_no_localized_printing_mirrored():
    db = get_sessionmaker()()
    try:
        collection = _make_collection(db)
        # DE requested, but nothing in scryfall_cards for this oracle_id at all.
        item = _make_item(db, collection, language="DE", resolved_oracle_id="unresolved-oracle")
        names = display_name_service.get_display_names(db, [item])
        assert names[item.id] == "Lightning Bolt"
    finally:
        db.rollback()
        db.close()


def test_falls_back_when_item_has_no_resolved_oracle_id():
    db = get_sessionmaker()()
    try:
        collection = _make_collection(db)
        item = _make_item(db, collection, language="DE", resolved_oracle_id=None)
        names = display_name_service.get_display_names(db, [item])
        assert names[item.id] == "Lightning Bolt"
    finally:
        db.rollback()
        db.close()


def test_override_language_wins_over_item_language():
    db = get_sessionmaker()()
    try:
        card = _seed_card(
            db,
            id="22222222-2222-2222-2222-222222222222",
            lang="de",
            printed_name="Blitzschlag",
        )
        collection = _make_collection(db)
        # Item's own language says EN, but a global override forces DE.
        item = _make_item(db, collection, language="EN", resolved_oracle_id=card.oracle_id)
        names = display_name_service.get_display_names(db, [item], override_language="de")
        assert names[item.id] == "Blitzschlag"
    finally:
        db.rollback()
        db.close()


def test_no_item_language_defaults_to_english():
    db = get_sessionmaker()()
    try:
        collection = _make_collection(db)
        item = _make_item(db, collection, language=None, resolved_oracle_id="oracle-1")
        names = display_name_service.get_display_names(db, [item])
        assert names[item.id] == "Lightning Bolt"
    finally:
        db.rollback()
        db.close()
