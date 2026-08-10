from __future__ import annotations

import json
import lzma
from decimal import Decimal

import pytest
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.models.pricing import PriceObservation, PriceProvider, PriceSyncState, PriceSyncStatus
from app.models.scryfall import ScryfallCard
from app.source_adapters import mtgjson as mtgjson_adapter

MTGJSON_UUID = "00010d56-fe38-5e35-8aed-518019aa36a5"
SCRYFALL_ID = "e3285e6b-3e79-4d7c-bf96-d920f973b122"

IDENTIFIERS_FIXTURE = {
    "meta": {"date": "2026-08-10", "version": "5.3.0"},
    "data": {
        MTGJSON_UUID: {"identifiers": {"scryfallId": SCRYFALL_ID}},
        "no-scryfall-id-uuid": {"identifiers": {}},
    },
}

PRICES_FIXTURE = {
    "meta": {"date": "2026-08-10", "version": "5.3.0"},
    "data": {
        MTGJSON_UUID: {
            "paper": {
                "tcgplayer": {"retail": {"normal": {"2026-08-10": 2.5}, "foil": {"2026-08-10": 10.0}}, "currency": "USD"},
                "cardmarket": {"retail": {"normal": {"2026-08-10": 2.0}}, "currency": "EUR"},
            }
        },
        "unmapped-uuid-not-in-identifiers": {"paper": {"tcgplayer": {"retail": {"normal": {"2026-08-10": 5.0}}}}},
    },
}


def _real_scryfall_card(scryfall_id: str = SCRYFALL_ID) -> ScryfallCard:
    return ScryfallCard(
        id=scryfall_id, oracle_id="4457ed35-7c10-48c8-9776-456485fdf070", name="Lightning Bolt",
        set_code="LEA", set_name="Limited Edition Alpha", collector_number="161", lang="en", layout="normal",
    )


def test_map_prices_extracts_usd_and_eur():
    rows = mtgjson_adapter._map_prices(SCRYFALL_ID, PRICES_FIXTURE["data"][MTGJSON_UUID])
    by_key = {(r["currency"], r["foil"]): r["price"] for r in rows}
    assert by_key[("USD", False)] == Decimal("2.5")
    assert by_key[("USD", True)] == Decimal("10.0")
    assert by_key[("EUR", False)] == Decimal("2.0")
    assert ("EUR", True) not in by_key
    assert all(r["provider"] == PriceProvider.mtgjson.value for r in rows)


def test_map_prices_no_paper_key_returns_empty():
    assert mtgjson_adapter._map_prices(SCRYFALL_ID, {"mtgo": {}}) == []


def test_run_price_sync_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        mtgjson_adapter, "fetch_identifiers_map", lambda settings: {MTGJSON_UUID: SCRYFALL_ID}
    )
    monkeypatch.setattr(
        mtgjson_adapter, "fetch_prices_today", lambda settings: PRICES_FIXTURE["data"]
    )

    db = get_sessionmaker()()
    try:
        db.add(_real_scryfall_card())
        db.commit()

        state = mtgjson_adapter.run_price_sync(db)
        assert state.status == PriceSyncStatus.current.value
        assert state.price_count == 3  # usd, usd_foil, eur - eur_foil absent
        assert state.error_message is None

        rows = db.query(PriceObservation).filter(PriceObservation.scryfall_card_id == SCRYFALL_ID).all()
        assert len(rows) == 3
        assert all(r.provider == PriceProvider.mtgjson.value for r in rows)
    finally:
        db.close()


def test_run_price_sync_dedupes_multiple_mtgjson_uuids_sharing_a_scryfall_id(monkeypatch: pytest.MonkeyPatch):
    """Real bug found against live MTGJSON data: more than one mtgjson uuid
    can map to the same scryfallId (e.g. distinct promo/variation entries
    MTGJSON tracks separately) - inserting both would violate
    price_observations' (card, provider, currency, foil) unique constraint.
    """
    other_uuid = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(
        mtgjson_adapter,
        "fetch_identifiers_map",
        lambda settings: {MTGJSON_UUID: SCRYFALL_ID, other_uuid: SCRYFALL_ID},
    )
    bolt_prices = {
        "paper": {
            "tcgplayer": {"retail": {"normal": {"2026-08-10": 2.5}, "foil": {"2026-08-10": 10.0}}, "currency": "USD"},
            "cardmarket": {"retail": {"normal": {"2026-08-10": 2.0}}, "currency": "EUR"},
        }
    }
    monkeypatch.setattr(
        mtgjson_adapter,
        "fetch_prices_today",
        lambda settings: {
            MTGJSON_UUID: bolt_prices,
            other_uuid: {
                "paper": {"tcgplayer": {"retail": {"normal": {"2026-08-10": 99.0}}, "currency": "USD"}}
            },
        },
    )

    db = get_sessionmaker()()
    try:
        db.add(_real_scryfall_card())
        db.commit()

        state = mtgjson_adapter.run_price_sync(db)
        assert state.status == PriceSyncStatus.current.value

        rows = db.query(PriceObservation).filter(
            PriceObservation.scryfall_card_id == SCRYFALL_ID, PriceObservation.currency == "USD",
            PriceObservation.foil.is_(False),
        ).all()
        assert len(rows) == 1  # not two conflicting rows for the same (card, provider, currency, foil)
    finally:
        db.close()


def test_run_price_sync_skips_cards_not_in_scryfall_mirror(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        mtgjson_adapter, "fetch_identifiers_map", lambda settings: {MTGJSON_UUID: SCRYFALL_ID}
    )
    monkeypatch.setattr(mtgjson_adapter, "fetch_prices_today", lambda settings: PRICES_FIXTURE["data"])

    db = get_sessionmaker()()
    try:
        # No ScryfallCard row for SCRYFALL_ID this time - the price data
        # references a printing our mirror doesn't know about.
        state = mtgjson_adapter.run_price_sync(db)
        assert state.status == PriceSyncStatus.current.value
        assert state.price_count == 0
        assert db.query(PriceObservation).count() == 0
    finally:
        db.close()


def test_run_price_sync_failure_records_error(monkeypatch: pytest.MonkeyPatch):
    def _boom(settings: object) -> dict[str, str]:
        raise mtgjson_adapter.MtgjsonSyncError("identifiers fetch failed")

    monkeypatch.setattr(mtgjson_adapter, "fetch_identifiers_map", _boom)

    db = get_sessionmaker()()
    try:
        with pytest.raises(mtgjson_adapter.MtgjsonSyncError):
            mtgjson_adapter.run_price_sync(db)

        state = db.get(PriceSyncState, PriceProvider.mtgjson.value)
        assert state is not None
        assert state.status == PriceSyncStatus.failed.value
        assert "identifiers fetch failed" in (state.error_message or "")
    finally:
        db.close()


def test_fetch_identifiers_map_real_xz_decompression(monkeypatch: pytest.MonkeyPatch):
    """Exercises the real lzma decompress + json parse path (not mocked),
    against a small synthetic .xz payload shaped like the real file.
    """
    payload = json.dumps(IDENTIFIERS_FIXTURE).encode()
    compressed = lzma.compress(payload)

    class _FakeResponse:
        content = compressed

        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(mtgjson_adapter.httpx, "get", lambda url, **kwargs: _FakeResponse())

    mapping = mtgjson_adapter.fetch_identifiers_map(get_settings())
    assert mapping == {MTGJSON_UUID: SCRYFALL_ID}
    assert "no-scryfall-id-uuid" not in mapping
