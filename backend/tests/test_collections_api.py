from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_default_collection_is_created_on_first_call():
    resp = client.get("/api/collections/default")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is True
    assert body["name"] == "My Collection"

    resp2 = client.get("/api/collections/default")
    assert resp2.json()["id"] == body["id"]  # idempotent, not a new collection each call


def test_create_and_list_collections():
    # Seed a first collection so "Trade binder" below is provably not it —
    # the first collection ever created for a user is auto-marked default.
    client.get("/api/collections/default")

    resp = client.post("/api/collections", json={"name": "Trade binder"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "Trade binder"
    assert created["is_default"] is False

    resp = client.get("/api/collections")
    names = {c["name"] for c in resp.json()}
    assert "Trade binder" in names
    assert "My Collection" in names


def test_get_unknown_collection_404():
    resp = client.get("/api/collections/999999")
    assert resp.status_code == 404


def test_items_of_empty_collection_is_empty_list():
    created = client.post("/api/collections", json={"name": "Empty one"}).json()
    resp = client.get(f"/api/collections/{created['id']}/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_items_of_unknown_collection_404():
    resp = client.get("/api/collections/999999/items")
    assert resp.status_code == 404
