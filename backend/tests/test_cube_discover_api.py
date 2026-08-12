from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.main import app
from app.models.cubecobra import PopularCube
from app.parsers.common import ParsedRow, ParseResult
from app.source_adapters import cubecobra
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.errors import SourceFetchError
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_cube(**overrides: object) -> PopularCube:
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
        cube = PopularCube(**defaults)
        db.add(cube)
        db.commit()
        db.refresh(cube)
        return cube
    finally:
        db.close()


def _fetch_result() -> DeckFetchResult:
    return DeckFetchResult(
        deck_name=None,
        parse_result=ParseResult(
            rows=[
                ParsedRow(
                    row_number=1,
                    raw={"name": "Sol Ring"},
                    mapped={
                        "name": "Sol Ring", "quantity": 1, "set_code": None, "set_name": None,
                        "collector_number": None, "language": None, "scryfall_id": None, "section": "mainboard",
                        "category": None, "tags": None, "foil": False,
                    },
                )
            ]
        ),
    )


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


def test_import_cube_success(monkeypatch: pytest.MonkeyPatch):
    cube = _seed_cube(external_id="import-me", name="Import Me")
    monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result())

    resp = client.post(f"/api/cube-discover/cubes/{cube.id}/import")
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported_list_id"] is not None
    assert body["import_error"] is None


def test_import_cube_failure_returns_200_with_error(monkeypatch: pytest.MonkeyPatch):
    cube = _seed_cube(external_id="fail-me", name="Fail Me")

    def _boom(url: str, user_agent: str) -> DeckFetchResult:
        raise SourceFetchError("cubecobra unreachable")

    monkeypatch.setattr(cubecobra, "fetch_and_parse", _boom)

    resp = client.post(f"/api/cube-discover/cubes/{cube.id}/import")
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported_list_id"] is None
    assert "cubecobra unreachable" in body["import_error"]


def test_import_cube_404_for_unknown_cube():
    resp = client.post("/api/cube-discover/cubes/999999/import")
    assert resp.status_code == 404
