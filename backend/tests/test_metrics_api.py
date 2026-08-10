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
