from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.collection import Collection, CollectionItem
from app.models.scryfall import ScryfallCard
from app.models.user import DEFAULT_USER_ID
from app.services import comparison_service


def _seed(db) -> Collection:
    card = ScryfallCard(
        id="e3285e6b-3e79-4d7c-bf96-d920f973b122",
        oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
        name="Lightning Bolt",
        set_code="LEA",
        set_name="Limited Edition Alpha",
        collector_number="161",
        lang="en",
        layout="normal",
    )
    db.add(card)
    collection = Collection(user_id=DEFAULT_USER_ID, name="Test", is_default=True)
    db.add(collection)
    db.flush()
    db.add(
        CollectionItem(
            collection_id=collection.id,
            card_name="Lightning Bolt",
            quantity=2,
            resolved_oracle_id=card.oracle_id,
            resolved_scryfall_card_id=card.id,
        )
    )
    db.commit()
    return collection


def test_text_list_fully_buildable():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        run = comparison_service.run_comparison(
            db, collection_id=collection.id, source_type="text_list", content="2 Lightning Bolt\n"
        )
        assert run.result.is_fully_buildable is True
        assert run.row_errors == []
    finally:
        db.close()


def test_text_list_reports_missing_and_row_errors():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        content = "4 Lightning Bolt\nnot a valid line\n"
        run = comparison_service.run_comparison(
            db, collection_id=collection.id, source_type="text_list", content=content
        )
        assert run.result.is_fully_buildable is False
        assert run.result.missing[0].missing_quantity == 2
        assert len(run.row_errors) == 1
        assert run.row_errors[0].row_number == 2
    finally:
        db.close()


def test_json_source_type_works():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        content = '{"cards": [{"name": "Lightning Bolt", "quantity": 1}]}'
        run = comparison_service.run_comparison(
            db, collection_id=collection.id, source_type="json", content=content
        )
        assert run.result.is_fully_buildable is True
    finally:
        db.close()


def test_generic_csv_with_column_mapping():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        content = "MyName,MyQty\nLightning Bolt,2\n"
        run = comparison_service.run_comparison(
            db,
            collection_id=collection.id,
            source_type="generic_csv",
            content=content,
            column_mapping={"name": "MyName", "quantity": "MyQty"},
        )
        assert run.result.is_fully_buildable is True
    finally:
        db.close()


def test_printing_mode():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        content = "1 Lightning Bolt (LEA) 161\n"
        run = comparison_service.run_comparison(
            db, collection_id=collection.id, source_type="text_list", content=content, mode="printing"
        )
        assert run.result.mode == "printing"
        assert run.result.is_fully_buildable is True
    finally:
        db.close()


def test_unsupported_source_type_raises():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        with pytest.raises(comparison_service.UnsupportedSourceTypeError):
            comparison_service.run_comparison(
                db, collection_id=collection.id, source_type="manabox_csv", content="Name,Quantity\nA,1\n"
            )
    finally:
        db.close()


def test_invalid_mode_raises():
    db = get_sessionmaker()()
    try:
        collection = _seed(db)
        with pytest.raises(comparison_service.InvalidComparisonModeError):
            comparison_service.run_comparison(
                db,
                collection_id=collection.id,
                source_type="text_list",
                content="1 Lightning Bolt\n",
                mode="nonsense",
            )
    finally:
        db.close()
