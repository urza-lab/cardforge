from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.cubecobra import PopularCube
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_cube(**overrides: object) -> None:
    defaults: dict[str, object] = {
        "external_id": "abc",
        "short_id": "topcube",
        "name": "Top Cube",
        "owner_username": "Alice",
        "source_url": "https://cubecobra.com/cube/list/topcube",
        "card_count": 360,
        "like_count": 100,
        "tags": ["legacy"],
    }
    defaults.update(overrides)
    db = get_sessionmaker()()
    try:
        db.add(PopularCube(**defaults))
        db.commit()
    finally:
        db.close()


def test_status_starts_not_started():
    resp = client.get("/api/cube-discover/cubes/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["cube_count"] == 0


def test_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/cube-discover/cubes/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/cube-discover/cubes/sync")
    assert second.status_code == 409


def test_list_cubes_empty():
    resp = client.get("/api/cube-discover/cubes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_cubes_sorted_by_likes_and_cards():
    _seed_cube(external_id="a", name="A", like_count=50, card_count=500)
    _seed_cube(external_id="b", name="B", like_count=500, card_count=100)

    by_likes = client.get("/api/cube-discover/cubes?sort=likes").json()
    assert [c["name"] for c in by_likes] == ["B", "A"]

    by_cards = client.get("/api/cube-discover/cubes?sort=cards").json()
    assert [c["name"] for c in by_cards] == ["A", "B"]
