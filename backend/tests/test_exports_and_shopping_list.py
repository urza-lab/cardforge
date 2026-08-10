from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _create_list(name: str = "Test Deck") -> int:
    resp = client.post("/api/lists", json={"name": name, "list_type": "deck"})
    id_: int = resp.json()["id"]
    return id_


def _import_text(list_id: int, content: str) -> None:
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200


def _import_collection_csv(collection_id: int, content: str) -> None:
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("c.csv", content.encode(), "text/csv")},
    ).json()
    confirm = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200


def test_list_csv_export():
    list_id = _create_list("Export Deck")
    _import_text(list_id, "4 Lightning Bolt\nCommander:\n1 Atraxa, Praetors' Voice\n")

    resp = client.get(f"/api/lists/{list_id}/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    assert "Lightning Bolt" in body
    assert "Atraxa" in body
    assert "commander" in body


def test_list_csv_export_unknown_list_404():
    resp = client.get("/api/lists/999999/export.csv")
    assert resp.status_code == 404


def test_collection_csv_export():
    collection_id = client.get("/api/collections/default").json()["id"]
    _import_collection_csv(collection_id, "Name,Quantity,Condition\nSol Ring,1,near_mint\n")

    resp = client.get(f"/api/collections/{collection_id}/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Sol Ring" in resp.text
    assert "NM" in resp.text


def test_shopping_list_across_two_decks_shares_owned_pool():
    collection_id = client.get("/api/collections/default").json()["id"]
    _import_collection_csv(collection_id, "Name,Quantity\nSol Ring,1\n")

    deck_a = _create_list("Deck A")
    _import_text(deck_a, "1 Sol Ring\n")
    deck_b = _create_list("Deck B")
    _import_text(deck_b, "1 Sol Ring\n")

    resp = client.get("/api/shopping-list", params={"list_ids": f"{deck_a},{deck_b}"})
    assert resp.status_code == 200
    body = resp.json()
    # Only 1 Sol Ring owned but 2 decks each want 1 - one of the two
    # requirements must show up as needing 1 more; the pool isn't double-counted.
    assert body["is_fully_buildable"] is False
    total_missing = sum(m["missing_quantity"] for m in body["missing"])
    assert total_missing == 1


def test_shopping_list_requires_list_ids():
    resp = client.get("/api/shopping-list", params={"list_ids": ""})
    assert resp.status_code == 400


def test_shopping_list_unknown_list_404():
    resp = client.get("/api/shopping-list", params={"list_ids": "999999"})
    assert resp.status_code == 404
