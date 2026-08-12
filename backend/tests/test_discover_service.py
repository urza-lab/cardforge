from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.discover import (
    DISCOVERY_SYNC_STATE_ID,
    DeckDiscoverySyncState,
    MoxfieldCommanderCache,
    PopularDeck,
)
from app.services import discover_service
from app.source_adapters import moxfield
from app.source_adapters.common import PopularDeckEntry


def _entry(external_id: str, source: str, *, main_card_id: str | None = None) -> PopularDeckEntry:
    return PopularDeckEntry(
        external_id=external_id,
        name=f"Deck {external_id}",
        author="Alice",
        source_url=f"https://{source}.example/decks/{external_id}",
        format="commander",
        view_count=100,
        like_count=10,
        color_identity=["W"],
        main_card_id=main_card_id,
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


def test_run_discovery_sync_resolves_moxfield_commanders(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [
            ("moxfield", lambda user_agent, **kw: [_entry("mox-1", "moxfield", main_card_id="E5bmd")]),
            ("archidekt", lambda user_agent, **kw: []),
        ],
    )
    monkeypatch.setattr(
        moxfield, "iter_resolved_commander_names", lambda ids, user_agent, known=None: iter([("E5bmd", "Winota, Joiner of Forces")])
    )

    db = get_sessionmaker()()
    try:
        state = discover_service.run_discovery_sync(db)
        assert state.status == "CURRENT"

        deck = db.query(PopularDeck).filter_by(external_id="mox-1").one()
        assert deck.commander_name == "Winota, Joiner of Forces"

        cached = db.get(MoxfieldCommanderCache, "E5bmd")
        assert cached is not None
        assert cached.name == "Winota, Joiner of Forces"
    finally:
        db.close()


def test_run_discovery_sync_skips_already_cached_commanders(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        db.add(MoxfieldCommanderCache(main_card_id="E5bmd", name="Winota, Joiner of Forces"))
        db.commit()
    finally:
        db.close()

    calls: list[set[str]] = []

    def fake_resolve(ids, user_agent, known=None):
        calls.append(set(ids) - set(known or {}))
        return iter(())

    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [
            ("moxfield", lambda user_agent, **kw: [_entry("mox-1", "moxfield", main_card_id="E5bmd")]),
            ("archidekt", lambda user_agent, **kw: []),
        ],
    )
    monkeypatch.setattr(moxfield, "iter_resolved_commander_names", fake_resolve)

    db = get_sessionmaker()()
    try:
        discover_service.run_discovery_sync(db)
        deck = db.query(PopularDeck).filter_by(external_id="mox-1").one()
        assert deck.commander_name == "Winota, Joiner of Forces"  # served from the cache, not re-fetched
    finally:
        db.close()

    assert calls == [set()]  # nothing left to fetch - already known


def test_run_discovery_sync_commander_resolution_failure_is_a_warning_not_a_failure(monkeypatch: pytest.MonkeyPatch):
    def _boom(ids, user_agent, known=None):
        raise RuntimeError("moxfield card lookup unreachable")

    monkeypatch.setattr(
        discover_service,
        "_SOURCES",
        [
            ("moxfield", lambda user_agent, **kw: [_entry("mox-1", "moxfield", main_card_id="E5bmd")]),
            ("archidekt", lambda user_agent, **kw: [_entry("ark-1", "archidekt")]),
        ],
    )
    monkeypatch.setattr(moxfield, "iter_resolved_commander_names", _boom)

    db = get_sessionmaker()()
    try:
        state = discover_service.run_discovery_sync(db)
        # Both sources' deck data still landed - a commander-resolution
        # hiccup is real to report but must not look like a total outage.
        assert state.status == "CURRENT"
        assert state.deck_count == 2
        assert "moxfield card lookup unreachable" in (state.error_message or "")

        deck = db.query(PopularDeck).filter_by(external_id="mox-1").one()
        assert deck.commander_name is None
    finally:
        db.close()
