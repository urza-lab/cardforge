from __future__ import annotations

import contextlib
import gzip
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.pricing import PriceObservation, PriceProvider
from app.models.scryfall import SYNC_STATE_ID, ScryfallCard, ScryfallSyncState, ScryfallSyncStatus
from app.source_adapters import scryfall as scryfall_adapter

# A tiny, realistic subset of default_cards JSONL objects: one plain card,
# one double-faced card (fields split across card_faces), one excluded
# layout (token) that must be dropped rather than stored.
BOLT: dict[str, Any] = {
    "id": "e3285e6b-3e79-4d7c-bf96-d920f973b122",
    "oracle_id": "4457ed35-7c10-48c8-9776-456485fdf070",
    "name": "Lightning Bolt",
    "set": "lea",
    "set_name": "Limited Edition Alpha",
    "collector_number": "161",
    "lang": "en",
    "layout": "normal",
    "mana_cost": "{R}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "colors": ["R"],
    "color_identity": ["R"],
    "rarity": "common",
    "foil": True,
    "nonfoil": True,
    "released_at": "1993-08-05",
    "prices": {"usd": "2.50", "usd_foil": "10.00", "eur": "2.00", "eur_foil": None, "tix": "0.05"},
}

DELVER: dict[str, Any] = {
    "id": "11111111-1111-1111-1111-111111111111",
    "oracle_id": "22222222-2222-2222-2222-222222222222",
    "name": "Delver of Secrets // Insectile Aberration",
    "set": "isd",
    "set_name": "Innistrad",
    "collector_number": "51",
    "lang": "en",
    "layout": "transform",
    "cmc": 1.0,
    "colors": None,
    "color_identity": ["U"],
    "rarity": "common",
    "foil": True,
    "nonfoil": True,
    "released_at": "2011-09-30",
    "card_faces": [
        {
            "name": "Delver of Secrets",
            "mana_cost": "{U}",
            "oracle_text": "At the beginning of your upkeep, look at the top card of your library...",
            "colors": ["U"],
        },
        {
            "name": "Insectile Aberration",
            "mana_cost": "",
            "oracle_text": "Flying",
            "colors": ["U"],
        },
    ],
}

TOKEN: dict[str, Any] = {
    "id": "33333333-3333-3333-3333-333333333333",
    "oracle_id": "44444444-4444-4444-4444-444444444444",
    "name": "Soldier",
    "set": "tisd",
    "set_name": "Innistrad Tokens",
    "collector_number": "1",
    "lang": "en",
    "layout": "token",
}


def test_map_card_basic_fields():
    mapped = scryfall_adapter._map_card(BOLT)
    assert mapped is not None
    assert mapped["id"] == BOLT["id"]
    assert mapped["oracle_id"] == BOLT["oracle_id"]
    assert mapped["set_code"] == "LEA"
    assert mapped["mana_cost"] == "{R}"
    assert mapped["colors"] == ["R"]


def test_map_card_joins_double_faced_fields():
    mapped = scryfall_adapter._map_card(DELVER)
    assert mapped is not None
    # The back face's mana_cost is "" (falsy) and correctly dropped from the
    # join rather than producing a trailing "{U} // ".
    assert mapped["mana_cost"] == "{U}"
    assert "Flying" in mapped["oracle_text"]
    assert "upkeep" in mapped["oracle_text"]
    assert mapped["colors"] == ["U"]  # falls back to the first face


def test_map_card_excludes_token_layout():
    assert scryfall_adapter._map_card(TOKEN) is None


def test_map_prices_extracts_four_fields_skips_null_and_etched_tix():
    rows = scryfall_adapter._map_prices(BOLT)
    by_key = {(r["currency"], r["foil"]): r["price"] for r in rows}
    assert by_key[("USD", False)] == Decimal("2.50")
    assert by_key[("USD", True)] == Decimal("10.00")
    assert by_key[("EUR", False)] == Decimal("2.00")
    assert ("EUR", True) not in by_key  # eur_foil was null
    assert len(rows) == 3
    assert all(r["provider"] == PriceProvider.scryfall.value for r in rows)


def test_map_prices_no_prices_key_returns_empty():
    assert scryfall_adapter._map_prices(DELVER) == []


def _write_gz_jsonl(path: Path, objects: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj) + "\n")


def test_iter_cards_from_file(tmp_path: Path):
    path = tmp_path / "cards.jsonl.gz"
    _write_gz_jsonl(path, [BOLT, DELVER])
    cards = list(scryfall_adapter.iter_cards_from_file(path))
    assert [c["name"] for c in cards] == [BOLT["name"], DELVER["name"]]


def test_run_bulk_sync_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture_path = tmp_path / "source.jsonl.gz"
    _write_gz_jsonl(fixture_path, [BOLT, DELVER, TOKEN])

    monkeypatch.setattr(
        scryfall_adapter,
        "fetch_bulk_manifest",
        lambda settings: {"jsonl_download_uri": "https://example.invalid/x.jsonl.gz", "updated_at": "2026-01-01T00:00:00.000+00:00"},
    )
    monkeypatch.setattr(
        scryfall_adapter,
        "download_bulk_file",
        lambda uri, dest, settings: dest.write_bytes(fixture_path.read_bytes()),
    )
    # Without an explicit scryfall_cache_dir here, run_bulk_sync would write
    # to the *real* Settings default (/data/scryfall_cache) - the same host
    # directory the actual running app uses - and overwrite the real ~110k-row
    # bulk file with this test's 3-line fixture. Route it into tmp_path instead.
    test_settings = get_settings().model_copy(update={"scryfall_cache_dir": str(tmp_path)})

    db = get_sessionmaker()()
    try:
        state = scryfall_adapter.run_bulk_sync(db, settings=test_settings)
        assert state.status == ScryfallSyncStatus.current.value
        assert state.card_count == 2  # TOKEN is excluded
        assert state.error_message is None

        names = {row.name for row in db.query(ScryfallCard).all()}
        assert names == {BOLT["name"], DELVER["name"]}

        prices = db.query(PriceObservation).filter(PriceObservation.scryfall_card_id == BOLT["id"]).all()
        assert {(p.currency, p.foil, p.price) for p in prices} == {
            ("USD", False, Decimal("2.50")),
            ("USD", True, Decimal("10.00")),
            ("EUR", False, Decimal("2.00")),
        }
        assert all(p.provider == PriceProvider.scryfall.value for p in prices)
    finally:
        db.close()


def test_run_bulk_sync_flushes_cards_before_prices_when_price_batch_fills_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Real ForeignKeyViolation found against a real sync: each card
    contributes up to 4 price rows but only 1 card row, so price_batch can
    reach BATCH_SIZE well before the card batch does - inserting it first
    referenced scryfall_card_ids whose ScryfallCard row was still sitting
    unflushed in the card batch. Reproduced deterministically here with a
    tiny BATCH_SIZE and two 4-priced-field cards (price_batch hits size 4
    after just the first card, while the card batch is still only at 1).
    """
    card_a = {**BOLT, "id": "aaaaaaaa-0000-0000-0000-000000000000", "oracle_id": "aaaaaaaa-1111-1111-1111-111111111111"}
    card_b = {**BOLT, "id": "bbbbbbbb-0000-0000-0000-000000000000", "oracle_id": "bbbbbbbb-1111-1111-1111-111111111111"}
    fixture_path = tmp_path / "source.jsonl.gz"
    _write_gz_jsonl(fixture_path, [card_a, card_b])

    monkeypatch.setattr(scryfall_adapter, "BATCH_SIZE", 3)
    monkeypatch.setattr(
        scryfall_adapter,
        "fetch_bulk_manifest",
        lambda settings: {"jsonl_download_uri": "https://example.invalid/x.jsonl.gz", "updated_at": "2026-01-01T00:00:00.000+00:00"},
    )
    monkeypatch.setattr(
        scryfall_adapter, "download_bulk_file", lambda uri, dest, settings: dest.write_bytes(fixture_path.read_bytes())
    )
    test_settings = get_settings().model_copy(update={"scryfall_cache_dir": str(tmp_path)})

    db = get_sessionmaker()()
    try:
        state = scryfall_adapter.run_bulk_sync(db, settings=test_settings)
        assert state.status == ScryfallSyncStatus.current.value
        assert state.error_message is None
        assert db.query(PriceObservation).filter(PriceObservation.scryfall_card_id == card_a["id"]).count() == 3
    finally:
        db.close()


def test_run_bulk_sync_preserves_non_scryfall_prices_for_surviving_printings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture_path = tmp_path / "source.jsonl.gz"
    _write_gz_jsonl(fixture_path, [BOLT])

    monkeypatch.setattr(
        scryfall_adapter,
        "fetch_bulk_manifest",
        lambda settings: {"jsonl_download_uri": "https://example.invalid/x.jsonl.gz", "updated_at": "2026-01-01T00:00:00.000+00:00"},
    )
    monkeypatch.setattr(
        scryfall_adapter, "download_bulk_file", lambda uri, dest, settings: dest.write_bytes(fixture_path.read_bytes())
    )
    test_settings = get_settings().model_copy(update={"scryfall_cache_dir": str(tmp_path)})

    db = get_sessionmaker()()
    try:
        # A manual price on BOLT, set before BOLT's own scryfall_cards row
        # even exists yet in this test - insert the card first so the FK is
        # satisfiable, matching how a real manual entry would only ever be
        # created against an already-mirrored card.
        db.add(
            ScryfallCard(
                id=BOLT["id"], oracle_id=BOLT["oracle_id"], name=BOLT["name"], set_code="LEA",
                set_name="Limited Edition Alpha", collector_number="161", lang="en", layout="normal",
            )
        )
        db.commit()
        db.add(
            PriceObservation(
                scryfall_card_id=BOLT["id"], provider=PriceProvider.manual.value, currency="USD",
                foil=False, price=Decimal("999.99"),
            )
        )
        db.commit()

        scryfall_adapter.run_bulk_sync(db, settings=test_settings)

        manual = (
            db.query(PriceObservation)
            .filter(PriceObservation.scryfall_card_id == BOLT["id"], PriceObservation.provider == "manual")
            .one_or_none()
        )
        assert manual is not None
        assert manual.price == Decimal("999.99")
        # The scryfall-provider price for the same card was also (re)created
        # in the same sync, independent of the preserved manual one.
        scryfall_price = (
            db.query(PriceObservation)
            .filter(PriceObservation.scryfall_card_id == BOLT["id"], PriceObservation.provider == "scryfall")
            .count()
        )
        assert scryfall_price > 0
    finally:
        db.close()


def test_run_bulk_sync_drops_non_scryfall_prices_for_removed_printings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture_path = tmp_path / "source.jsonl.gz"
    _write_gz_jsonl(fixture_path, [DELVER])  # BOLT is absent from this sync - "removed"

    monkeypatch.setattr(
        scryfall_adapter,
        "fetch_bulk_manifest",
        lambda settings: {"jsonl_download_uri": "https://example.invalid/x.jsonl.gz", "updated_at": "2026-01-01T00:00:00.000+00:00"},
    )
    monkeypatch.setattr(
        scryfall_adapter, "download_bulk_file", lambda uri, dest, settings: dest.write_bytes(fixture_path.read_bytes())
    )
    test_settings = get_settings().model_copy(update={"scryfall_cache_dir": str(tmp_path)})

    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id=BOLT["id"], oracle_id=BOLT["oracle_id"], name=BOLT["name"], set_code="LEA",
                set_name="Limited Edition Alpha", collector_number="161", lang="en", layout="normal",
            )
        )
        db.commit()
        db.add(
            PriceObservation(
                scryfall_card_id=BOLT["id"], provider=PriceProvider.manual.value, currency="USD",
                foil=False, price=Decimal("999.99"),
            )
        )
        db.commit()

        scryfall_adapter.run_bulk_sync(db, settings=test_settings)

        # BOLT's scryfall_cards row is gone (not in this sync's data), so
        # its manual price observation is correctly gone too via CASCADE -
        # not silently kept referencing a printing that no longer exists.
        assert db.get(ScryfallCard, BOLT["id"]) is None
        assert db.query(PriceObservation).filter(PriceObservation.scryfall_card_id == BOLT["id"]).count() == 0
    finally:
        db.close()


def test_run_bulk_sync_failure_preserves_previous_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        db.add(
            ScryfallCard(
                id=BOLT["id"],
                oracle_id=BOLT["oracle_id"],
                name=BOLT["name"],
                set_code="LEA",
                set_name="Limited Edition Alpha",
                collector_number="161",
                lang="en",
                layout="normal",
            )
        )
        db.commit()

        def _boom(settings: object) -> dict[str, Any]:
            raise scryfall_adapter.ScryfallSyncError("manifest fetch failed")

        monkeypatch.setattr(scryfall_adapter, "fetch_bulk_manifest", _boom)

        with contextlib.suppress(scryfall_adapter.ScryfallSyncError):
            scryfall_adapter.run_bulk_sync(db)

        state = db.get(ScryfallSyncState, SYNC_STATE_ID)
        assert state is not None
        assert state.status == ScryfallSyncStatus.failed.value
        assert "manifest fetch failed" in (state.error_message or "")

        # The previously-synced card must still be there - a failed sync
        # never wipes out data from a prior successful one.
        assert db.get(ScryfallCard, BOLT["id"]) is not None
    finally:
        db.close()
