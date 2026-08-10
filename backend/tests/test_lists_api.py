from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_create_and_list_lists():
    resp = client.post("/api/lists", json={"name": "Atraxa Superfriends", "list_type": "deck"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Atraxa Superfriends"
    assert body["list_type"] == "deck"

    listed = client.get("/api/lists").json()
    assert any(item["name"] == "Atraxa Superfriends" for item in listed)


def test_create_cube():
    resp = client.post("/api/lists", json={"name": "Vintage Cube", "list_type": "cube"})
    assert resp.status_code == 201
    assert resp.json()["list_type"] == "cube"


def test_invalid_list_type_rejected():
    resp = client.post("/api/lists", json={"name": "Bad", "list_type": "nonsense"})
    assert resp.status_code == 400


def test_get_unknown_list_404():
    resp = client.get("/api/lists/999999")
    assert resp.status_code == 404


def test_items_of_empty_list_is_empty():
    created = client.post("/api/lists", json={"name": "Empty Deck", "list_type": "deck"}).json()
    resp = client.get(f"/api/lists/{created['id']}/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_list():
    created = client.post("/api/lists", json={"name": "Throwaway", "list_type": "deck"}).json()
    resp = client.delete(f"/api/lists/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/lists/{created['id']}").status_code == 404


def test_delete_list_with_import_history():
    # Regression test: deleting a list that has a confirmed ListImport (and
    # therefore items with source_import_id set) used to 500 - the ORM tried
    # to null out list_imports.list_id (a NOT NULL column) instead of
    # trusting the FK's own ON DELETE CASCADE. See app.models.lists.CardList.
    created = client.post("/api/lists", json={"name": "Throwaway With History", "list_type": "deck"}).json()
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(created["id"])},
        files={"file": ("deck.txt", b"1 Sol Ring\n", "text/plain")},
    ).json()
    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200

    resp = client.delete(f"/api/lists/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/lists/{created['id']}").status_code == 404


def test_delete_unknown_list_404():
    resp = client.delete("/api/lists/999999")
    assert resp.status_code == 404


def test_comparison_on_empty_list_is_fully_buildable():
    created = client.post("/api/lists", json={"name": "Empty", "list_type": "deck"}).json()
    resp = client.get(f"/api/lists/{created['id']}/comparison")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_fully_buildable"] is True
    assert body["total_required_cards"] == 0


def test_comparison_unknown_list_404():
    resp = client.get("/api/lists/999999/comparison")
    assert resp.status_code == 404


def test_comparison_invalid_mode_400():
    created = client.post("/api/lists", json={"name": "Test", "list_type": "deck"}).json()
    resp = client.get(f"/api/lists/{created['id']}/comparison", params={"mode": "nonsense"})
    assert resp.status_code == 400
