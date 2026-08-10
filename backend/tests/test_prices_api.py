from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.scryfall import ScryfallCard
from fastapi.testclient import TestClient

client = TestClient(app)

BOLT_ID = "e3285e6b-3e79-4d7c-bf96-d920f973b122"


def _seed_bolt() -> None:
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id=BOLT_ID, oracle_id="4457ed35-7c10-48c8-9776-456485fdf070", name="Lightning Bolt",
                set_code="LEA", set_name="Limited Edition Alpha", collector_number="161", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()


def test_mtgjson_status_starts_not_started():
    resp = client.get("/api/mtgjson/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_STARTED"
    assert body["price_count"] == 0


def test_mtgjson_trigger_sync_marks_fetching_and_enqueues():
    resp = client.post("/api/mtgjson/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "FETCHING"

    second = client.post("/api/mtgjson/sync")
    assert second.status_code == 409


def test_default_price_profile_bootstraps():
    resp = client.get("/api/price-profiles/default")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is True
    assert body["provider_priority"] == ["manual", "mtgjson", "scryfall"]

    again = client.get("/api/price-profiles/default")
    assert again.json()["id"] == body["id"]


def test_create_list_get_update_delete_price_profile():
    created = client.post(
        "/api/price-profiles",
        json={"name": "EUR Budget", "currency": "eur", "provider_priority": ["mtgjson"], "prefer_foil": False},
    )
    assert created.status_code == 201
    profile = created.json()
    assert profile["currency"] == "EUR"

    listed = client.get("/api/price-profiles").json()
    assert any(p["id"] == profile["id"] for p in listed)

    fetched = client.get(f"/api/price-profiles/{profile['id']}")
    assert fetched.status_code == 200

    updated = client.put(f"/api/price-profiles/{profile['id']}", json={"prefer_foil": True})
    assert updated.status_code == 200
    assert updated.json()["prefer_foil"] is True

    deleted = client.delete(f"/api/price-profiles/{profile['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/price-profiles/{profile['id']}").status_code == 404


def test_create_price_profile_invalid_provider_400():
    resp = client.post(
        "/api/price-profiles", json={"name": "Bad", "currency": "USD", "provider_priority": ["ebay"]}
    )
    assert resp.status_code == 400


def test_manual_price_set_get_resolve_clear():
    _seed_bolt()

    set_resp = client.post(
        "/api/prices/manual", json={"scryfall_card_id": BOLT_ID, "currency": "USD", "foil": False, "price": "3.50"}
    )
    assert set_resp.status_code == 201
    assert set_resp.json()["price"] == "3.50"

    observations = client.get(f"/api/prices/{BOLT_ID}").json()
    assert len(observations) == 1
    assert observations[0]["provider"] == "manual"

    resolved = client.get(f"/api/prices/{BOLT_ID}/resolve").json()
    assert resolved["price"] == "3.50"
    assert resolved["provider"] == "manual"

    cleared = client.delete(f"/api/prices/manual?scryfall_card_id={BOLT_ID}&currency=USD&foil=false")
    assert cleared.status_code == 204
    assert client.get(f"/api/prices/{BOLT_ID}").json() == []


def test_manual_price_unknown_card_404():
    resp = client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": "00000000-0000-0000-0000-000000000000", "currency": "USD", "price": "1.00"},
    )
    assert resp.status_code == 404


def test_resolve_price_no_match_returns_null_price():
    _seed_bolt()
    resolved = client.get(f"/api/prices/{BOLT_ID}/resolve").json()
    assert resolved["price"] is None
    assert resolved["provider"] is None
