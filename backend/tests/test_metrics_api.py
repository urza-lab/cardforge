from __future__ import annotations

from app.core.database import get_sessionmaker
from app.main import app
from app.models.scryfall import ScryfallCard
from fastapi.testclient import TestClient

client = TestClient(app)


def test_metrics_endpoint_returns_prometheus_text_format():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "cardforge_collection_items_total" in body
    assert "cardforge_scryfall_sync_up" in body
    assert "cardforge_mtgjson_sync_up" in body


def test_metrics_reflects_real_collection_size():
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="e3285e6b-3e79-4d7c-bf96-d920f973b122", oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt", set_code="LEA", set_name="Limited Edition Alpha",
                collector_number="161", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    collection_id = client.get("/api/collections/default").json()["id"]
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("c.csv", b"Name,Quantity\nLightning Bolt,3\n", "text/csv")},
    ).json()
    client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    body = client.get("/metrics").text
    assert "cardforge_collection_items_total 1.0" in body
    assert "cardforge_collection_quantity_total 3.0" in body


def test_metrics_includes_price_observations_by_provider():
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="e3285e6b-3e79-4d7c-bf96-d920f973b122", oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt", set_code="LEA", set_name="Limited Edition Alpha",
                collector_number="161", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": "e3285e6b-3e79-4d7c-bf96-d920f973b122", "currency": "USD", "price": "2.50"},
    )

    body = client.get("/metrics").text
    assert 'cardforge_price_observations_total{provider="manual"} 1.0' in body


def test_metrics_includes_per_list_coverage_percent():
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="1f0d2e46-25e6-4415-8c00-53abaf7de520", oracle_id="6ad8011d-3471-4369-9d68-b264cc027487",
                name="Sol Ring", set_code="C21", set_name="Commander 2021",
                collector_number="263", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    list_id = client.post("/api/lists", json={"name": "Metrics Test Deck", "list_type": "deck"}).json()["id"]
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Sol Ring\n", "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    body = client.get("/metrics").text
    assert (
        f'cardforge_list_coverage_percent{{list_id="{list_id}",list_name="Metrics Test Deck",list_type="deck"}} 0.0'
        in body
    )


def test_metrics_includes_missing_cost_when_every_missing_card_is_priced():
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="1f0d2e46-25e6-4415-8c00-53abaf7de520", oracle_id="6ad8011d-3471-4369-9d68-b264cc027487",
                name="Sol Ring", set_code="C21", set_name="Commander 2021",
                collector_number="263", lang="en", layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    client.post(
        "/api/prices/manual",
        json={"scryfall_card_id": "1f0d2e46-25e6-4415-8c00-53abaf7de520", "currency": "USD", "price": "2.50"},
    )

    list_id = client.post("/api/lists", json={"name": "Priced Test Deck", "list_type": "deck"}).json()["id"]
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"2 Sol Ring\n", "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    body = client.get("/metrics").text
    assert (
        f'cardforge_list_missing_cost{{currency="USD",list_id="{list_id}",'
        f'list_name="Priced Test Deck",list_type="deck"}} 5.0'
        in body
    )


def test_metrics_omits_missing_cost_when_a_missing_card_has_no_price():
    list_id = client.post("/api/lists", json={"name": "Unpriced Test Deck", "list_type": "deck"}).json()["id"]
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Some Unpriced Card\n", "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": True})

    body = client.get("/metrics").text
    for line in body.splitlines():
        if line.startswith("cardforge_list_missing_cost{") and f'list_id="{list_id}"' in line:
            raise AssertionError(f"unpriced list should not appear in cardforge_list_missing_cost: {line}")
