from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.edhrec import EDHREC_SYNC_STATE_ID, EdhrecSyncState, SynthesizedDeck
from app.services import edhrec_service
from app.source_adapters import edhrec
from app.source_adapters.errors import SourceFetchError


def _commander(slug: str) -> edhrec.CommanderRef:
    return edhrec.CommanderRef(slug=slug, name=f"Commander {slug}", rank=1, num_decks=100)


def _entry(slug: str) -> edhrec.SynthesizedDeckEntry:
    return edhrec.SynthesizedDeckEntry(
        commander_slug=slug, commander_name=f"Commander {slug}", rank=1, num_decks=100,
        color_identity=["W"], card_count=99, deck_text=f"Commander: Commander {slug}\nSol Ring",
        source_url=f"https://edhrec.com/commanders/{slug}",
    )


def test_run_edhrec_sync_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec, "fetch_popular_commanders", lambda user_agent, **kw: [_commander("a"), _commander("b")])
    monkeypatch.setattr(edhrec, "fetch_and_synthesize_all", lambda commanders, user_agent: ([_entry("a"), _entry("b")], []))

    db = get_sessionmaker()()
    try:
        state = edhrec_service.run_edhrec_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 2
        assert state.error_message is None
        assert db.query(SynthesizedDeck).count() == 2
    finally:
        db.close()


def test_run_edhrec_sync_partial_failure_stays_current(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec, "fetch_popular_commanders", lambda user_agent, **kw: [_commander("a"), _commander("b")])
    monkeypatch.setattr(
        edhrec, "fetch_and_synthesize_all", lambda commanders, user_agent: ([_entry("a")], ["b: page fetch failed"])
    )

    db = get_sessionmaker()()
    try:
        state = edhrec_service.run_edhrec_sync(db)
        assert state.status == "CURRENT"
        assert state.deck_count == 1
        assert "b: page fetch failed" in (state.error_message or "")
    finally:
        db.close()


def test_run_edhrec_sync_total_failure_marks_failed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(edhrec, "fetch_popular_commanders", lambda user_agent, **kw: [_commander("a")])
    monkeypatch.setattr(edhrec, "fetch_and_synthesize_all", lambda commanders, user_agent: ([], ["a: page fetch failed"]))

    db = get_sessionmaker()()
    try:
        with pytest.raises(RuntimeError):
            edhrec_service.run_edhrec_sync(db)

        state = db.get(EdhrecSyncState, EDHREC_SYNC_STATE_ID)
        assert state is not None
        assert state.status == "FAILED"
    finally:
        db.close()


def test_run_edhrec_sync_commander_list_fetch_failure_marks_failed(monkeypatch: pytest.MonkeyPatch):
    def _boom(user_agent: str, **kw: object) -> list[edhrec.CommanderRef]:
        raise SourceFetchError("commanders page unreachable")

    monkeypatch.setattr(edhrec, "fetch_popular_commanders", _boom)

    db = get_sessionmaker()()
    try:
        with pytest.raises(SourceFetchError):
            edhrec_service.run_edhrec_sync(db)

        state = db.get(EdhrecSyncState, EDHREC_SYNC_STATE_ID)
        assert state is not None
        assert state.status == "FAILED"
        assert "commanders page unreachable" in (state.error_message or "")
    finally:
        db.close()
