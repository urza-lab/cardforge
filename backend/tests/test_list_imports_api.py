from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _create_list(name: str = "Test Deck") -> int:
    resp = client.post("/api/lists", json={"name": name, "list_type": "deck"})
    id_: int = resp.json()["id"]
    return id_


def test_text_preview_confirm_flow():
    list_id = _create_list()
    content = "4 Lightning Bolt\n1 Sol Ring\nCommander:\n1 Atraxa, Praetors' Voice\n"

    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    )
    assert resp.status_code == 201
    preview = resp.json()
    assert preview["error_rows"] == 0
    assert preview["valid_rows"] == 3

    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"
    assert confirm.json()["imported_rows"] == 3

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert len(items) == 3
    commander = next(i for i in items if i["card_name"] == "Atraxa, Praetors' Voice")
    assert commander["section"] == "commander"
    mainboard_bolt = next(i for i in items if i["card_name"] == "Lightning Bolt")
    assert mainboard_bolt["section"] == "mainboard"
    assert mainboard_bolt["quantity"] == 4


def test_json_preview_confirm_flow_with_category_and_tags():
    list_id = _create_list("Cube Test")
    content = '{"cards": [{"name": "Sol Ring", "quantity": 1, "category": "Ramp", "tags": ["fast-mana"]}]}'

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "json", "list_id": str(list_id)},
        files={"file": ("cube.json", content.encode(), "application/json")},
    ).json()
    assert preview["error_rows"] == 0

    confirm = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items[0]["category"] == "Ramp"
    assert items[0]["tags"] == ["fast-mana"]


def test_confirm_with_error_rows_requires_skip_bad_rows():
    list_id = _create_list()
    content = "4 Lightning Bolt\n0 Bad Quantity\n"

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    assert preview["error_rows"] == 1

    refused = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert refused.status_code == 400

    ok = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": True})
    assert ok.status_code == 200
    assert ok.json()["status"] == "partially_confirmed"


def test_abort_leaves_list_untouched():
    list_id = _create_list()
    content = "1 Abort Me\n"

    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()

    aborted = client.post(f"/api/list-imports/{preview['id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["status"] == "aborted"

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items == []

    resp = client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert resp.status_code == 409


def test_duplicate_upload_is_flagged_after_confirm():
    list_id = _create_list()
    content = "1 Sol Ring\n"

    first = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{first['id']}/confirm", json={"skip_bad_rows": False})

    second = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", content.encode(), "text/plain")},
    ).json()
    assert second["is_likely_duplicate"] is True
    assert second["duplicate_of_import_id"] == first["id"]


def test_preview_unknown_source_type_400():
    list_id = _create_list()
    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "manabox_csv", "list_id": str(list_id)},
        files={"file": ("x.txt", b"1 Sol Ring\n", "text/plain")},
    )
    assert resp.status_code == 400


def test_preview_unknown_list_404():
    resp = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": "999999"},
        files={"file": ("x.txt", b"1 Sol Ring\n", "text/plain")},
    )
    assert resp.status_code == 404


def test_imported_items_are_resolved_against_scryfall():
    from app.core.database import get_sessionmaker
    from app.models.scryfall import ScryfallCard

    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id="e3285e6b-3e79-4d7c-bf96-d920f973b122",
                oracle_id="4457ed35-7c10-48c8-9776-456485fdf070",
                name="Lightning Bolt",
                set_code="LEA",
                set_name="Limited Edition Alpha",
                collector_number="161",
                lang="en",
                layout="normal",
            )
        )
        db.commit()
    finally:
        db.close()

    list_id = _create_list()
    preview = client.post(
        "/api/list-imports/preview",
        data={"source_type": "text", "list_id": str(list_id)},
        files={"file": ("deck.txt", b"1 Lightning Bolt\n", "text/plain")},
    ).json()
    client.post(f"/api/list-imports/{preview['id']}/confirm", json={"skip_bad_rows": False})

    items = client.get(f"/api/lists/{list_id}/items").json()
    assert items[0]["resolved_oracle_id"] == "4457ed35-7c10-48c8-9776-456485fdf070"
