from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.collection import Collection, CollectionItem
from app.models.mtgjson_precons import PRECON_SYNC_STATE_ID, PreconDeck, PreconSyncState
from app.models.user import DEFAULT_USER_ID
from app.services import precon_service
from app.source_adapters import mtgjson_precons
from app.source_adapters.errors import SourceFetchError


def _entry(file_name: str, cards: list[dict]) -> mtgjson_precons.PreconDeckEntry:
    return mtgjson_precons.PreconDeckEntry(
        file_name=file_name,
        name=f"Deck {file_name}",
        commander_names=["Some Commander"],
        release_date="2024-01-01",
        source_url=f"https://mtgjson.com/api/v5/decks/{file_name}.json",
        card_count=sum(c["quantity"] for c in cards),
        cards=cards,
        deck_text="name,quantity,scryfall_id,section\n",
    )


def _collection(db) -> Collection:
    collection = Collection(user_id=DEFAULT_USER_ID, name="Test", is_default=True)
    db.add(collection)
    db.flush()
    db.add(CollectionItem(collection_id=collection.id, card_name="Sol Ring", quantity=1, resolved_oracle_id="sol-ring-oracle"))
    db.commit()
    return collection


def test_run_precon_sync_success(monkeypatch: pytest.MonkeyPatch):
    entries = [
        _entry("DeckA", [{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}]),
        _entry("DeckB", [{"name": "Mana Crypt", "oracle_id": "mana-crypt-oracle", "quantity": 1}]),
    ]
    monkeypatch.setattr(mtgjson_precons, "fetch_precon_decks", lambda user_agent: (entries, []))

    db = get_sessionmaker()()
    try:
        state = precon_service.run_precon_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 2
        assert state.error_message is None
        assert db.query(PreconDeck).count() == 2
    finally:
        db.close()


def test_run_precon_sync_partial_failure_stays_current(monkeypatch: pytest.MonkeyPatch):
    entries = [_entry("DeckA", [{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}])]
    monkeypatch.setattr(mtgjson_precons, "fetch_precon_decks", lambda user_agent: (entries, ["DeckB: HTTP 500"]))

    db = get_sessionmaker()()
    try:
        state = precon_service.run_precon_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 1
        assert "DeckB: HTTP 500" in (state.error_message or "")
    finally:
        db.close()


def test_run_precon_sync_total_failure_marks_failed(monkeypatch: pytest.MonkeyPatch):
    def _boom(user_agent: str) -> tuple[list, list]:
        raise SourceFetchError("DeckList.json unreachable")

    monkeypatch.setattr(mtgjson_precons, "fetch_precon_decks", _boom)

    db = get_sessionmaker()()
    try:
        with pytest.raises(SourceFetchError):
            precon_service.run_precon_sync(db)

        state = db.get(PreconSyncState, PRECON_SYNC_STATE_ID)
        assert state is not None
        assert state.status == "FAILED"
        assert "DeckList.json unreachable" in (state.error_message or "")
    finally:
        db.close()


def test_list_precon_decks_with_coverage_ranks_by_coverage(monkeypatch: pytest.MonkeyPatch):
    entries = [
        _entry(
            "FullyOwned",
            [{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}],
        ),
        _entry(
            "PartiallyOwned",
            [
                {"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1},
                {"name": "Mana Crypt", "oracle_id": "mana-crypt-oracle", "quantity": 1},
            ],
        ),
    ]
    monkeypatch.setattr(mtgjson_precons, "fetch_precon_decks", lambda user_agent: (entries, []))

    db = get_sessionmaker()()
    try:
        precon_service.run_precon_sync(db)
        collection = _collection(db)

        ranked = precon_service.list_precon_decks_with_coverage(db, collection_id=collection.id)

        assert [r.deck.file_name for r in ranked] == ["FullyOwned", "PartiallyOwned"]
        assert ranked[0].coverage_percent == 100.0
        assert ranked[0].is_fully_buildable is True
        assert ranked[0].missing_count == 0
        assert ranked[1].coverage_percent == 50.0
        assert ranked[1].is_fully_buildable is False
        assert ranked[1].missing_count == 1
    finally:
        db.close()
