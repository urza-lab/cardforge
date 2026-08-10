from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _seed_scryfall_card() -> None:
    from app.core.database import get_sessionmaker
    from app.models.scryfall import ScryfallCard

    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="e3285e6b-3e79-4d7c-bf96-d920f973b122",
                oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt",
                printed_name=None,
                set_code="LEA",
                set_name="Limited Edition Alpha",
                collector_number="161",
                lang="en",
                layout="normal",
            )
        )
        db.add(
            ScryfallCard(
                id="11111111-1111-1111-1111-111111111111",
                oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt",
                printed_name="Blitzschlag",
                set_code="4ed",
                set_name="Fourth Edition",
                collector_number="161",
                lang="de",
                layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()


def test_collection_item_display_name_defaults_to_item_language():
    _seed_scryfall_card()
    collection_id = client.get("/api/collections/default").json()["id"]
    content = b"Name,Quantity,Language,Scryfall ID\nLightning Bolt,1,DE,11111111-1111-1111-1111-111111111111\n"
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("x.csv", content, "text/csv")},
    ).json()
    client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    items = client.get(f"/api/collections/{collection_id}/items").json()
    assert items[0]["display_name"] == "Blitzschlag"
    assert items[0]["card_name"] == "Lightning Bolt"


def test_collection_item_display_name_respects_force_override():
    _seed_scryfall_card()
    collection_id = client.get("/api/collections/default").json()["id"]
    content = b"Name,Quantity,Language,Scryfall ID\nLightning Bolt,1,EN,e3285e6b-3e79-4d7c-bf96-d920f973b122\n"
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("x.csv", content, "text/csv")},
    ).json()
    client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    # Without an override, the item's own EN language means the English name.
    items = client.get(f"/api/collections/{collection_id}/items").json()
    assert items[0]["display_name"] == "Lightning Bolt"

    client.put("/api/settings", json={"card_name_language": "de"})
    items = client.get(f"/api/collections/{collection_id}/items").json()
    assert items[0]["display_name"] == "Blitzschlag"


def test_settings_card_name_language_round_trip():
    resp = client.get("/api/settings")
    assert resp.json()["card_name_language"] is None

    resp = client.put("/api/settings", json={"card_name_language": "de"})
    assert resp.status_code == 200
    assert resp.json()["card_name_language"] == "de"

    # Explicit null clears it back to auto.
    resp = client.put("/api/settings", json={"card_name_language": None})
    assert resp.json()["card_name_language"] is None


def test_settings_invalid_card_name_language_rejected():
    resp = client.put("/api/settings", json={"card_name_language": "fr"})
    assert resp.status_code == 400


def test_list_item_display_name():
    _seed_scryfall_card()
    created = client.post("/api/lists", json={"name": "Test", "list_type": "deck"}).json()
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "json", "list_id": str(created["id"])},
        files={
            "file": (
                "d.json",
                b'{"cards": [{"name": "Lightning Bolt", "quantity": 1, "scryfall_id": "11111111-1111-1111-1111-111111111111"}]}',
                "application/json",
            )
        },
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    items = client.get(f"/api/lists/{created['id']}/items").json()
    # No per-item language on the list item (json import didn't set one) -
    # defaults to English, so display_name stays the English name here.
    assert items[0]["display_name"] == "Lightning Bolt"
