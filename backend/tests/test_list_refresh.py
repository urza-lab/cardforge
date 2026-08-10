from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.database import get_sessionmaker
from app.main import app
from app.models.lists import CardList, ListRefreshStatus
from app.services import list_refresh_service
from app.source_adapters import moxfield
from fastapi.testclient import TestClient

client = TestClient(app)


def _moxfield_response(status_code: int, json_body: object = None) -> httpx.Response:
    request = httpx.Request("GET", "https://api.moxfield.com/v2/decks/all/x")
    if json_body is not None:
        return httpx.Response(status_code, content=json.dumps(json_body), request=request)
    return httpx.Response(status_code, request=request)


def _deck(cards: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "name": "Refresh Test Deck",
        "mainboard": cards,
        "sideboard": {},
        "maybeboard": {},
        "commanders": {},
        "companions": {},
    }


_SOL_RING_ONLY = _deck(
    {
        "Sol Ring": {
            "quantity": 1,
            "isFoil": False,
            "card": {
                "name": "Sol Ring",
                "scryfall_id": "1f0d2e46-25e6-4415-8c00-53abaf7de520",
                "set": "c21",
                "set_name": "Commander 2021",
                "cn": "263",
            },
        },
    }
)

_SOL_RING_PLUS_LOTUS = _deck(
    {
        "Sol Ring": {
            "quantity": 1,
            "isFoil": False,
            "card": {
                "name": "Sol Ring",
                "scryfall_id": "1f0d2e46-25e6-4415-8c00-53abaf7de520",
                "set": "c21",
                "set_name": "Commander 2021",
                "cn": "263",
            },
        },
        "Black Lotus": {
            "quantity": 1,
            "isFoil": False,
            "card": {
                "name": "Black Lotus",
                "scryfall_id": "bd8fa327-dd41-4737-8f19-2cf5eb1f7cdd",
                "set": "lea",
                "set_name": "Limited Edition Alpha",
                "cn": "232",
            },
        },
    }
)


def _create_url_sourced_list(name: str = "Refresh Test") -> int:
    list_id: int = client.post("/api/lists", json={"name": name, "list_type": "deck"}).json()["id"]
    preview = client.post(
        "/api/list-imports/preview-url",
        json={"list_id": list_id, "url": "https://moxfield.com/decks/refresh-test"},
    ).json()
    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    return list_id


def test_refresh_manual_list_returns_400():
    list_id = client.post("/api/lists", json={"name": "Manual Only", "list_type": "deck"}).json()["id"]
    resp = client.post(f"/api/lists/{list_id}/refresh")
    assert resp.status_code == 400


def test_refresh_unknown_list_404():
    resp = client.post("/api/lists/999999/refresh")
    assert resp.status_code == 404


def test_refresh_marks_fetching_and_enqueues(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()

    resp = client.post(f"/api/lists/{list_id}/refresh")
    assert resp.status_code == 202
    assert resp.json()["refresh_status"] == "FETCHING"

    status = client.get(f"/api/lists/{list_id}").json()
    assert status["refresh_status"] == "FETCHING"


def test_refresh_while_already_fetching_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()

    first = client.post(f"/api/lists/{list_id}/refresh")
    assert first.status_code == 202

    second = client.post(f"/api/lists/{list_id}/refresh")
    assert second.status_code == 409


def test_run_refresh_replaces_items_when_content_changed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()
    items = client.get(f"/api/lists/{list_id}/items").json()
    assert [i["card_name"] for i in items] == ["Sol Ring"]

    monkeypatch.setattr(
        moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_PLUS_LOTUS)
    )
    db = get_sessionmaker()()
    try:
        card_list = db.get(CardList, list_id)
        assert card_list is not None
        list_refresh_service.run_refresh(db, card_list)
        assert card_list.refresh_status == ListRefreshStatus.current.value
        assert card_list.last_refreshed_at is not None
    finally:
        db.close()

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert sorted(i["card_name"] for i in items) == ["Black Lotus", "Sol Ring"]


def test_run_refresh_is_a_noop_when_content_unchanged(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()
    items_before = client.get(f"/api/lists/{list_id}/items").json()
    first_refreshed_at = client.get(f"/api/lists/{list_id}").json()["last_refreshed_at"]

    db = get_sessionmaker()()
    try:
        card_list = db.get(CardList, list_id)
        assert card_list is not None
        list_refresh_service.run_refresh(db, card_list)
        assert card_list.refresh_status == ListRefreshStatus.current.value
    finally:
        db.close()

    items_after = client.get(f"/api/lists/{list_id}/items").json()
    assert [i["id"] for i in items_before] == [i["id"] for i in items_after]  # same rows, not replaced
    second_refreshed_at = client.get(f"/api/lists/{list_id}").json()["last_refreshed_at"]
    assert second_refreshed_at >= first_refreshed_at


def test_run_refresh_auth_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()

    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(403))
    db = get_sessionmaker()()
    try:
        card_list = db.get(CardList, list_id)
        assert card_list is not None
        list_refresh_service.run_refresh(db, card_list)
        assert card_list.refresh_status == ListRefreshStatus.auth_required.value
        assert card_list.refresh_error is not None
    finally:
        db.close()


def test_run_refresh_source_fetch_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(200, _SOL_RING_ONLY))
    list_id = _create_url_sourced_list()

    monkeypatch.setattr(moxfield, "guarded_get", lambda url, **kwargs: _moxfield_response(404))
    db = get_sessionmaker()()
    try:
        card_list = db.get(CardList, list_id)
        assert card_list is not None
        list_refresh_service.run_refresh(db, card_list)
        assert card_list.refresh_status == ListRefreshStatus.failed.value
        assert card_list.refresh_error is not None
    finally:
        db.close()


def test_is_stale_true_only_when_current_and_old():
    fresh = CardList(
        user_id=1,
        name="fresh",
        list_type="deck",
        source_url="https://moxfield.com/decks/x",
        source_type="moxfield",
        refresh_status=ListRefreshStatus.current.value,
        last_refreshed_at=datetime.now(UTC).replace(tzinfo=None),
    )
    assert list_refresh_service.is_stale(fresh) is False

    old_but_current = CardList(
        user_id=1,
        name="old",
        list_type="deck",
        source_url="https://moxfield.com/decks/x",
        source_type="moxfield",
        refresh_status=ListRefreshStatus.current.value,
        last_refreshed_at=(datetime.now(UTC) - timedelta(days=30)).replace(tzinfo=None),
    )
    assert list_refresh_service.is_stale(old_but_current) is True

    old_but_failed = CardList(
        user_id=1,
        name="old-failed",
        list_type="deck",
        source_url="https://moxfield.com/decks/x",
        source_type="moxfield",
        refresh_status=ListRefreshStatus.failed.value,
        last_refreshed_at=(datetime.now(UTC) - timedelta(days=30)).replace(tzinfo=None),
    )
    assert list_refresh_service.is_stale(old_but_failed) is False

    manual_list = CardList(user_id=1, name="manual", list_type="deck")
    assert list_refresh_service.is_stale(manual_list) is False
