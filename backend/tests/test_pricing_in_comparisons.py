from __future__ import annotations

from decimal import Decimal

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


def _create_list_with_missing_sol_ring() -> int:
    resp = client.post("/api/lists", json={"name": "Pricing Test", "list_type": "deck"})
    list_id: int = resp.json()["id"]
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Sol Ring\n", "text/plain")},
    ).json()
    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    return list_id


def test_comparison_without_price_profile_id_omits_pricing():
    _seed_sol_ring()
    list_id = _create_list_with_missing_sol_ring()

    resp = client.get(f"/api/lists/{list_id}/comparison")
    assert resp.status_code == 200
    body = resp.json()
    assert body["priced_missing"] is None
    assert body["budget"] is None


def test_comparison_with_price_profile_prices_missing_cards():
    _seed_sol_ring()
    list_id = _create_list_with_missing_sol_ring()
    client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": SOL_RING_ID, "currency": "USD", "foil": False, "price": "4.20"},
    )
    profile_id = client.get("/api/price-profiles/default").json()["id"]

    resp = client.get(f"/api/lists/{list_id}/comparison?price_profile_id={profile_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["priced_missing"] is not None
    priced = next(p for p in body["priced_missing"] if p["name"] == "Sol Ring")
    assert priced["unit_price"] == "4.20"
    assert priced["provider"] == "manual"
    assert body["budget"] is None  # no budget param given


def test_comparison_with_budget_returns_allocation():
    _seed_sol_ring()
    list_id = _create_list_with_missing_sol_ring()
    client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": SOL_RING_ID, "currency": "USD", "foil": False, "price": "4.20"},
    )
    profile_id = client.get("/api/price-profiles/default").json()["id"]

    resp = client.get(f"/api/lists/{list_id}/comparison?price_profile_id={profile_id}&budget=100")
    assert resp.status_code == 200
    budget = resp.json()["budget"]
    assert budget is not None
    assert budget["currency"] == "USD"
    assert Decimal(budget["total_spent"]) == Decimal("4.20")
    assert budget["fully_covered"] is True


def test_comparison_unknown_price_profile_404():
    _seed_sol_ring()
    list_id = _create_list_with_missing_sol_ring()
    resp = client.get(f"/api/lists/{list_id}/comparison?price_profile_id=999999")
    assert resp.status_code == 404


def test_shopping_list_with_budget():
    _seed_sol_ring()
    list_id = _create_list_with_missing_sol_ring()
    client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": SOL_RING_ID, "currency": "USD", "foil": False, "price": "4.20"},
    )
    profile_id = client.get("/api/price-profiles/default").json()["id"]

    resp = client.get(f"/api/shopping-list?list_ids={list_id}&price_profile_id={profile_id}&budget=1")
    assert resp.status_code == 200
    budget = resp.json()["budget"]
    assert budget is not None
    assert budget["fully_covered"] is False  # $1 budget can't cover a $4.20 card
