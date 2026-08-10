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


def test_list_comparison_against_default_collection():
    collection_id = client.get("/api/collections/default").json()["id"]
    _import_collection_csv(collection_id, "Name,Quantity\nLightning Bolt,2\n")

    list_id = _create_list()
    _import_text(list_id, "4 Lightning Bolt\n")

    resp = client.get(f"/api/lists/{list_id}/comparison")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_fully_buildable"] is False
    assert body["missing"][0]["missing_quantity"] == 2


def test_list_comparison_excludes_sideboard_from_requirements():
    collection_id = client.get("/api/collections/default").json()["id"]
    # Nothing imported into the collection - if sideboard counted, this would be "not buildable".
    list_id = _create_list()
    _import_text(list_id, "1 Lightning Bolt\nSideboard:\n1 Rest in Peace\n")

    resp = client.get(f"/api/lists/{list_id}/comparison", params={"collection_id": collection_id})
    assert resp.status_code == 200
    body = resp.json()
    # Only the mainboard "Lightning Bolt" counts as required; the sideboard
    # entry must not appear in `missing` even though nothing is owned.
    assert body["total_required_cards"] == 1
    assert all(m["name"] != "Rest in Peace" for m in body["missing"])


def test_list_comparison_explicit_collection_id():
    other = client.post("/api/collections", json={"name": "Other Collection"}).json()
    _import_collection_csv(other["id"], "Name,Quantity\nSol Ring,1\n")

    list_id = _create_list()
    _import_text(list_id, "1 Sol Ring\n")

    resp = client.get(f"/api/lists/{list_id}/comparison", params={"collection_id": other["id"]})
    assert resp.status_code == 200
    assert resp.json()["is_fully_buildable"] is True
