from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.discover import PopularDeck
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_deck(**overrides: object) -> None:
    defaults: dict[str, object] = {
        "source": "moxfield",
        "external_id": "abc",
        "name": "Test Deck",
        "author": "Alice",
        "source_url": "https://moxfield.com/decks/abc",
        "format": "commander",
        "view_count": 100,
        "like_count": 10,
        "color_identity": ["W", "U"],
    }
    defaults.update(overrides)
    db = get_sessionmaker()()
    try:
        db.add(PopularDeck(**defaults))
        db.commit()
    finally:
        db.close()


def test_status_starts_not_started():
    resp = client.get("/api/discover/decks/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["deck_count"] == 0


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/discover/decks/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/discover/decks/sync")
    assert second.status_code == 409


def test_list_decks_empty():
    resp = client.get("/api/discover/decks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_decks_sorted_by_views_and_likes():
    _seed_deck(external_id="a", name="A", view_count=50, like_count=200)
    _seed_deck(external_id="b", name="B", view_count=500, like_count=20)

    by_views = client.get("/api/discover/decks?sort=views").json()
    assert [d["name"] for d in by_views] == ["B", "A"]

    by_likes = client.get("/api/discover/decks?sort=likes").json()
    assert [d["name"] for d in by_likes] == ["A", "B"]


def test_list_decks_color_identity_filter():
    _seed_deck(external_id="mono-w", name="Mono W", color_identity=["W"])
    _seed_deck(external_id="wu", name="WU Deck", color_identity=["W", "U"])
    _seed_deck(external_id="wubrg", name="Five Color", color_identity=["W", "U", "B", "R", "G"])

    resp = client.get("/api/discover/decks?color_identity=WU").json()
    names = {d["name"] for d in resp}
    assert names == {"Mono W", "WU Deck"}  # subset-of-WU matches; 5c deck doesn't


def test_list_decks_source_filter():
    _seed_deck(external_id="mox-1", name="Mox Deck", source="moxfield")
    _seed_deck(external_id="ark-1", name="Ark Deck", source="archidekt")

    resp = client.get("/api/discover/decks?source=archidekt").json()
    assert [d["name"] for d in resp] == ["Ark Deck"]
