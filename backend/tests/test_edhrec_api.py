from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.edhrec import SynthesizedDeck
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_deck(**overrides: object) -> None:
    defaults: dict[str, object] = {
        "commander_slug": "test-commander",
        "commander_name": "Test Commander",
        "rank": 1,
        "num_decks": 100,
        "color_identity": ["W", "U"],
        "card_count": 99,
        "deck_text": "Commander: Test Commander\nSol Ring",
        "source_url": "https://edhrec.com/commanders/test-commander",
    }
    defaults.update(overrides)
    db = get_sessionmaker()()
    try:
        db.add(SynthesizedDeck(**defaults))
        db.commit()
    finally:
        db.close()


def test_status_starts_not_started():
    resp = client.get("/api/edhrec/decks/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["deck_count"] == 0


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/edhrec/decks/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/edhrec/decks/sync")
    assert second.status_code == 409


def test_list_decks_empty():
    resp = client.get("/api/edhrec/decks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_decks_sorted_by_num_decks_and_rank():
    _seed_deck(commander_slug="a", commander_name="A", rank=2, num_decks=50)
    _seed_deck(commander_slug="b", commander_name="B", rank=1, num_decks=500)

    by_num_decks = client.get("/api/edhrec/decks?sort=num_decks").json()
    assert [d["commander_name"] for d in by_num_decks] == ["B", "A"]

    by_rank = client.get("/api/edhrec/decks?sort=rank").json()
    assert [d["commander_name"] for d in by_rank] == ["B", "A"]


def test_list_decks_color_identity_filter():
    _seed_deck(commander_slug="mono-w", commander_name="Mono W", color_identity=["W"])
    _seed_deck(commander_slug="wu", commander_name="WU Commander", color_identity=["W", "U"])
    _seed_deck(commander_slug="wubrg", commander_name="Five Color", color_identity=["W", "U", "B", "R", "G"])

    resp = client.get("/api/edhrec/decks?color_identity=WU").json()
    names = {d["commander_name"] for d in resp}
    assert names == {"Mono W", "WU Commander"}
