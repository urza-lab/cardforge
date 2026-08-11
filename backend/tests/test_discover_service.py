from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.discover import DISCOVERY_SYNC_STATE_ID, DeckDiscoverySyncState, PopularDeck
from app.services import discover_service
from app.source_adapters.common import PopularDeckEntry


def _entry(external_id: str, source: str) -> PopularDeckEntry:
    return PopularDeckEntry(
        external_id=external_id,
        name=f"Deck {external_id}",
        author="Alice",
        source_url=f"https://{source}.example/decks/{external_id}",
        format="commander",
        view_count=100,
        like_count=10,
        color_identity=["W"],
    )


def test_run_discovery_sync_both_sources_succeed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [
            ("moxfield", lambda user_agent, **kw: [_entry("mox-1", "moxfield")]),
            ("archidekt", lambda user_agent, **kw: [_entry("ark-1", "archidekt")]),
        ],
    )

    db = get_sessionmaker()()
    try:
        state = discover_service.run_discovery_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 2
        assert state.error_message is None

        decks = {d.source: d for d in db.query(PopularDeck).all()}
        assert set(decks) == {"moxfield", "archidekt"}
    finally:
        db.close()


def test_run_discovery_sync_partial_failure_keeps_successful_source(monkeypatch: pytest.MonkeyPatch):
    def _boom(user_agent: str, **kw: object) -> list[PopularDeckEntry]:
        raise RuntimeError("moxfield search failed")

    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [
            ("moxfield", _boom),
            ("archidekt", lambda user_agent, **kw: [_entry("ark-1", "archidekt")]),
        ],
    )

    db = get_sessionmaker()()
    try:
        state = discover_service.run_discovery_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 1
        assert "moxfield search failed" in (state.error_message or "")

        decks = db.query(PopularDeck).all()
        assert len(decks) == 1
        assert decks[0].source == "archidekt"
    finally:
        db.close()


def test_run_discovery_sync_all_sources_fail(monkeypatch: pytest.MonkeyPatch):
    def _boom(name: str) -> object:
        def _fn(user_agent: str, **kw: object) -> list[PopularDeckEntry]:
            raise RuntimeError(f"{name} failed")

        return _fn

    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [("moxfield", _boom("moxfield")), ("archidekt", _boom("archidekt"))],
    )

    db = get_sessionmaker()()
    try:
        with pytest.raises(RuntimeError):
            discover_service.run_discovery_sync(db)

        state = db.get(DeckDiscoverySyncState, DISCOVERY_SYNC_STATE_ID)
        assert state is not None
        assert state.status == "FAILED"
        assert "moxfield failed" in (state.error_message or "")
        assert "archidekt failed" in (state.error_message or "")
    finally:
        db.close()
