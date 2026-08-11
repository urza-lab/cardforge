from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.collection import Collection, CollectionItem
from app.models.mtgjson_precons import PreconDeck
from app.models.user import DEFAULT_USER_ID
from app.services import collection_service
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_deck(**overrides: object) -> None:
    defaults: dict[str, object] = {
        "file_name": "TestDeck",
        "name": "Test Deck",
        "commander_names": ["Test Commander"],
        "release_date": "2024-01-01",
        "source_url": "https://mtgjson.com/api/v5/decks/TestDeck.json",
        "card_count": 1,
        "cards": [{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}],
        "deck_text": "name,quantity,scryfall_id,section\nSol Ring,1,,mainboard\n",
    }
    defaults.update(overrides)
    db = get_sessionmaker()()
    try:
        db.add(PreconDeck(**defaults))
        db.commit()
    finally:
        db.close()


def test_status_starts_not_started():
    resp = client.get("/api/precons/decks/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["deck_count"] == 0


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/precons/decks/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/precons/decks/sync")
    assert second.status_code == 409


def test_list_decks_empty():
    resp = client.get("/api/precons/decks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_decks_ranks_by_coverage_against_default_collection():
    db = get_sessionmaker()()
    try:
        collection = collection_service.get_or_create_default_collection(db, DEFAULT_USER_ID)
        db.add(CollectionItem(collection_id=collection.id, card_name="Sol Ring", quantity=1, resolved_oracle_id="sol-ring-oracle"))
        db.commit()
    finally:
        db.close()

    _seed_deck(file_name="Fully", name="Fully Owned", cards=[{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}])
    _seed_deck(
        file_name="Partial",
        name="Partially Owned",
        cards=[
            {"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1},
            {"name": "Mana Crypt", "oracle_id": "mana-crypt-oracle", "quantity": 1},
        ],
    )

    resp = client.get("/api/precons/decks")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["file_name"] for d in body] == ["Fully", "Partial"]
    assert body[0]["coverage_percent"] == 100.0
    assert body[0]["is_fully_buildable"] is True
    assert body[1]["coverage_percent"] == 50.0
    assert body[1]["is_fully_buildable"] is False


def test_list_decks_respects_limit():
    _seed_deck(file_name="A", name="A")
    _seed_deck(file_name="B", name="B")

    resp = client.get("/api/precons/decks?limit=1")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_decks_explicit_collection_id():
    db = get_sessionmaker()()
    try:
        collection = Collection(user_id=DEFAULT_USER_ID, name="Other", is_default=False)
        db.add(collection)
        db.flush()
        db.add(CollectionItem(collection_id=collection.id, card_name="Sol Ring", quantity=1, resolved_oracle_id="sol-ring-oracle"))
        db.commit()
        collection_id = collection.id
    finally:
        db.close()

    _seed_deck(file_name="Fully", cards=[{"name": "Sol Ring", "oracle_id": "sol-ring-oracle", "quantity": 1}])

    resp = client.get(f"/api/precons/decks?collection_id={collection_id}")
    assert resp.status_code == 200
    assert resp.json()[0]["coverage_percent"] == 100.0
