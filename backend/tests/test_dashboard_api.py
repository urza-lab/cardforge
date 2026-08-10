from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.scryfall import ScryfallCard
from fastapi.testclient import TestClient

client = TestClient(app)

SOL_RING_ID = "1f0d2e46-25e6-4415-8c00-53abaf7de520"
SOL_RING_ORACLE_ID = "6ad8011d-3471-4369-9d68-b264cc027487"


def _seed_sol_ring() -> None:
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id=SOL_RING_ID, oracle_id=SOL_RING_ORACLE_ID, name="Sol Ring", set_code="C21",
                set_name="Commander 2021", collector_number="263", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()


def _create_list_with_missing_sol_ring(name: str = "Dashboard Test") -> int:
    resp = client.post("/api/lists", json={"name": name, "list_type": "deck"})
    list_id: int = resp.json()["id"]
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Sol Ring\n", "text/plain")},
    ).json()
    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    return list_id


def test_dashboard_empty_state():
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["collection_distinct_items"] == 0
    assert body["list_count"] == 0
    assert body["list_buildability"] == []
    assert body["top_leverage"] == []
    assert body["scryfall_sync_status"] == "NOT_STARTED"
    assert body["mtgjson_sync_status"] == "NOT_STARTED"


def test_dashboard_reflects_collection_and_lists():
    _seed_sol_ring()
    client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(client.get("/api/collections/default").json()["id"])},
        files={"file": ("c.csv", b"Name,Quantity,Scryfall ID\nSol Ring,1,1f0d2e46-25e6-4415-8c00-53abaf7de520\n", "text/csv")},
    )
    _create_list_with_missing_sol_ring()

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["list_count"] == 1
    assert len(body["list_buildability"]) == 1
    assert body["list_buildability"][0]["name"] == "Dashboard Test"


def test_dashboard_leverage_ranks_card_completing_a_deck():
    _seed_sol_ring()
    _create_list_with_missing_sol_ring()

    resp = client.get("/api/dashboard")
    body = resp.json()
    assert len(body["top_leverage"]) == 1
    candidate = body["top_leverage"][0]
    assert candidate["name"] == "Sol Ring"
    assert candidate["lists_newly_buildable"] == 1
    assert candidate["quantity_needed"] == 1
