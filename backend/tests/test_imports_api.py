from __future__ import annotations

import json

from app.main import app
from fastapi.testclient import TestClient

from tests.fixtures import EXAMPLES_DIR

client = TestClient(app)


def _default_collection_id() -> int:
    resp = client.get("/api/collections/default")
    id_: int = resp.json()["id"]
    return id_


def test_manabox_preview_confirm_flow():
    collection_id = _default_collection_id()
    content = (EXAMPLES_DIR / "manabox_collection.csv").read_bytes()

    resp = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("manabox_collection.csv", content, "text/csv")},
    )
    assert resp.status_code == 201
    preview = resp.json()
    assert preview["status"] == "previewed"
    assert preview["error_rows"] == 0
    assert preview["valid_rows"] == 5
    assert preview["is_likely_duplicate"] is False

    confirm = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"
    assert confirm.json()["imported_rows"] == 5

    items = client.get(f"/api/collections/{collection_id}/items").json()
    assert len(items) == 5
    assert any(i["card_name"] == "Lightning Bolt" and i["quantity"] == 4 for i in items)


def test_duplicate_upload_is_flagged_after_confirm():
    collection_id = _default_collection_id()
    content = (EXAMPLES_DIR / "collection_list.txt").read_bytes()

    first = client.post(
        "/api/imports/preview",
        data={"source_type": "text_list", "collection_id": str(collection_id)},
        files={"file": ("list.txt", content, "text/plain")},
    ).json()
    client.post(f"/api/imports/{first['id']}/confirm", json={"skip_bad_rows": False})

    second = client.post(
        "/api/imports/preview",
        data={"source_type": "text_list", "collection_id": str(collection_id)},
        files={"file": ("list.txt", content, "text/plain")},
    ).json()
    assert second["is_likely_duplicate"] is True
    assert second["duplicate_of_import_id"] == first["id"]


def test_confirm_with_error_rows_requires_explicit_skip_bad_rows():
    collection_id = _default_collection_id()
    content = b"Name,Quantity\nLightning Bolt,4\nBad Row,notanumber\n"

    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("bad.csv", content, "text/csv")},
    ).json()
    assert preview["error_rows"] == 1
    assert preview["valid_rows"] == 1

    refused = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert refused.status_code == 400

    # Nothing was written to the collection by the refused attempt above.
    assert client.get(f"/api/collections/{collection_id}/items").json() == []

    ok = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": True})
    assert ok.status_code == 200
    assert ok.json()["status"] == "partially_confirmed"
    assert ok.json()["imported_rows"] == 1


def test_abort_leaves_collection_untouched():
    collection_id = _default_collection_id()
    content = b"Name,Quantity\nAbort Me,1\n"

    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("abort.csv", content, "text/csv")},
    ).json()

    aborted = client.post(f"/api/imports/{preview['id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["status"] == "aborted"

    items = client.get(f"/api/collections/{collection_id}/items").json()
    assert not any(i["card_name"] == "Abort Me" for i in items)

    # An aborted import can't be confirmed afterwards.
    resp = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert resp.status_code == 409


def test_preview_unknown_source_type_400():
    collection_id = _default_collection_id()
    resp = client.post(
        "/api/imports/preview",
        data={"source_type": "nonsense", "collection_id": str(collection_id)},
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 400


def test_preview_unknown_collection_404():
    resp = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": "999999"},
        files={"file": ("x.csv", b"Name,Quantity\nFoo,1\n", "text/csv")},
    )
    assert resp.status_code == 404


def test_preview_empty_file_400():
    collection_id = _default_collection_id()
    resp = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400


def test_generic_csv_with_explicit_column_mapping():
    collection_id = _default_collection_id()
    content = b"MyName,MyQty\nBlack Lotus,1\n"

    resp = client.post(
        "/api/imports/preview",
        data={
            "source_type": "generic_csv",
            "collection_id": str(collection_id),
            "column_mapping": json.dumps({"name": "MyName", "quantity": "MyQty"}),
        },
        files={"file": ("weird.csv", content, "text/csv")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["error_rows"] == 0
    assert body["rows"][0]["mapped_data"]["name"] == "Black Lotus"


def test_json_import_confirms():
    collection_id = _default_collection_id()
    content = (EXAMPLES_DIR / "collection.json").read_bytes()

    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "json", "collection_id": str(collection_id)},
        files={"file": ("collection.json", content, "application/json")},
    ).json()
    assert preview["error_rows"] == 0

    confirm = client.post(f"/api/imports/{preview['id']}/confirm", json={"skip_bad_rows": False})
    assert confirm.status_code == 200
    assert confirm.json()["imported_rows"] == 3


def test_list_and_get_import():
    collection_id = _default_collection_id()
    preview = client.post(
        "/api/imports/preview",
        data={"source_type": "manabox_csv", "collection_id": str(collection_id)},
        files={"file": ("x.csv", b"Name,Quantity\nFoo,1\n", "text/csv")},
    ).json()

    listed = client.get("/api/imports", params={"collection_id": collection_id}).json()
    assert any(i["id"] == preview["id"] for i in listed)

    fetched = client.get(f"/api/imports/{preview['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["rows"][0]["mapped_data"]["name"] == "Foo"


def test_get_unknown_import_404():
    resp = client.get("/api/imports/999999")
    assert resp.status_code == 404
