from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.cubecobra import CUBE_DISCOVERY_SYNC_STATE_ID, CubeDiscoverySyncState, PopularCube
from app.models.lists import CardList
from app.models.user import DEFAULT_USER_ID
from app.parsers.common import ParsedRow, ParseResult
from app.services import cube_discover_service, list_service
from app.source_adapters import cubecobra
from app.source_adapters.common import DeckFetchResult
from app.source_adapters.cubecobra import PopularCubeEntry
from app.source_adapters.errors import SourceFetchError


def _entry(external_id: str, *, name: str | None = None) -> PopularCubeEntry:
    return PopularCubeEntry(
        external_id=external_id, short_id=external_id, name=name or f"Cube {external_id}", owner_username="Alice",
        source_url=f"https://cubecobra.com/cube/list/{external_id}", card_count=360, like_count=100, tags=None,
        num_decks=42, date_last_updated=None,
    )


def test_run_cube_discovery_sync_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a"), _entry("b")]
    )

    db = get_sessionmaker()()
    try:
        state = cube_discover_service.run_cube_discovery_sync(db)
        assert state.status == "CURRENT"
        assert state.cube_count == 2

        cubes = db.query(PopularCube).all()
        assert len(cubes) == 2
    finally:
        db.close()


def test_run_cube_discovery_sync_truncates_overlong_fields_instead_of_crashing(monkeypatch: pytest.MonkeyPatch):
    """Same real bug/fix as the full-scrape's own version - applied here
    too since this bulk insert has the identical unguarded shape, even
    though the regular sync's popularity-bounded range never happened to
    hit it live.
    """
    long_name = "X" * 300  # PopularCube.name is String(256)
    entry = PopularCubeEntry(
        external_id="a", short_id="a", name=long_name, owner_username="Alice",
        source_url="https://cubecobra.com/cube/list/a", card_count=360, like_count=100, tags=None,
        num_decks=42, date_last_updated=None,
    )
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [entry])

    db = get_sessionmaker()()
    try:
        state = cube_discover_service.run_cube_discovery_sync(db)
        assert state.status == "CURRENT"

        cube = db.query(PopularCube).filter_by(external_id="a").one()
        assert len(cube.name) == 256
    finally:
        db.close()


def test_run_cube_discovery_sync_failure_records_error(monkeypatch: pytest.MonkeyPatch):
    def _boom(user_agent: str, **kw: object) -> list[PopularCubeEntry]:
        raise SourceFetchError("search failed")

    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", _boom)

    db = get_sessionmaker()()
    try:
        with pytest.raises(SourceFetchError):
            cube_discover_service.run_cube_discovery_sync(db)

        state = db.get(CubeDiscoverySyncState, CUBE_DISCOVERY_SYNC_STATE_ID)
        assert state is not None
        assert state.status == "FAILED"
        assert "search failed" in (state.error_message or "")
    finally:
        db.close()


def test_run_cube_discovery_sync_preserves_import_state_across_resync(monkeypatch: pytest.MonkeyPatch):
    """A routine resync fully deletes and reinserts every PopularCube row -
    "already imported"/"failed, retry" must survive that (see
    app/models/cubecobra.py), matched back up by CubeCobra's own stable
    external_id, not lost the way it would be with a naive wipe.
    """
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])

    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()
        card_list = list_service.create_list(db, name="Cube a", list_type="cube")
        cube.imported_list_id = card_list.id
        db.commit()

        cube_discover_service.run_cube_discovery_sync(db)

        resynced = db.query(PopularCube).filter_by(external_id="a").one()
        assert resynced.id != cube.id  # a real new row, not the same one - proves this wasn't just skipped
        assert resynced.imported_list_id == card_list.id
    finally:
        db.close()


def test_run_full_cube_scrape_success_tracks_progress(monkeypatch: pytest.MonkeyPatch):
    def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
        yield [_entry("a"), _entry("b")], {"PK": "1"}
        yield [_entry("c")], None

    monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)

    db = get_sessionmaker()()
    try:
        state = cube_discover_service.run_full_cube_scrape(db)
        assert state.status == "COMPLETED"
        assert state.cubes_found == 3
        assert state.pages_fetched == 2
        assert state.last_progress_at is not None
        assert state.finished_at is not None
        assert state.last_key is None  # genuine exhaustion reached - nothing left to resume from

        cubes = db.query(PopularCube).all()
        assert {c.external_id for c in cubes} == {"a", "b", "c"}
    finally:
        db.close()


def test_run_full_cube_scrape_upserts_without_duplicates(monkeypatch: pytest.MonkeyPatch):
    """The same cube can legitimately reappear across pages (or across a
    retried scrape) - must update the existing row, never insert a second
    one, since external_id is the real, stable identity CubeCobra itself
    uses (see PopularCube's own unique constraint).
    """

    def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
        yield [_entry("a", name="Old Name")], {"PK": "1"}
        yield [_entry("a", name="New Name")], None  # same external_id, real update

    monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)

    db = get_sessionmaker()()
    try:
        cube_discover_service.run_full_cube_scrape(db)
        cubes = db.query(PopularCube).filter_by(external_id="a").all()
        assert len(cubes) == 1
        assert cubes[0].name == "New Name"
    finally:
        db.close()


def test_run_full_cube_scrape_preserves_import_state(monkeypatch: pytest.MonkeyPatch):
    """Unlike the regular sync's delete-then-reinsert (which needs an
    explicit snapshot/restore), the full scrape's upsert never touches
    imported_list_id/import_error/import_attempted_at at all - they should
    survive a rescrape for free, simply by never being in the upsert's
    `set_` clause.
    """
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])

    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()
        card_list = list_service.create_list(db, name="Cube a", list_type="cube")
        cube.imported_list_id = card_list.id
        db.commit()

        def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
            yield [_entry("a", name="Rescraped Name")], None

        monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)
        cube_discover_service.run_full_cube_scrape(db)

        rescraped = db.query(PopularCube).filter_by(external_id="a").one()
        assert rescraped.id == cube.id  # same row, not a new one - proves this was a real upsert
        assert rescraped.name == "Rescraped Name"
        assert rescraped.imported_list_id == card_list.id
    finally:
        db.close()


def test_run_full_cube_scrape_failure_records_error(monkeypatch: pytest.MonkeyPatch):
    def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
        yield [_entry("a")], {"PK": "resume-here"}
        raise SourceFetchError("connection reset")

    monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)

    db = get_sessionmaker()()
    try:
        with pytest.raises(SourceFetchError):
            cube_discover_service.run_full_cube_scrape(db)

        state = cube_discover_service.get_full_scrape_state(db)
        assert state.status == "FAILED"
        assert "connection reset" in (state.error_message or "")
        # The page fetched before the failure must still be committed - a
        # crash partway through must not lose progress already made.
        assert db.query(PopularCube).filter_by(external_id="a").one_or_none() is not None
        # The cursor from the last successful page must survive the failure
        # too - user-requested/found live: a retry needs this to resume
        # instead of re-walking from page 1 (see CLAUDE.md).
        assert state.last_key == '{"PK": "resume-here"}'
    finally:
        db.close()


def test_run_full_cube_scrape_resumes_from_persisted_cursor(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        state = cube_discover_service.get_full_scrape_state(db)
        state.last_key = '{"PK": "page-5"}'
        db.commit()
    finally:
        db.close()

    seen_start_keys: list[object] = []

    def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
        seen_start_keys.append(start_key)
        yield [_entry("resumed")], None

    monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)

    db = get_sessionmaker()()
    try:
        cube_discover_service.run_full_cube_scrape(db)
    finally:
        db.close()

    assert seen_start_keys == [{"PK": "page-5"}]


def test_run_full_cube_scrape_truncates_overlong_fields_instead_of_crashing(monkeypatch: pytest.MonkeyPatch):
    """Real bug found live 34,554 cubes into a real full-catalog scrape: a
    real cube's name/username can simply be longer than the column allows
    (the bounded, popularity-limited sync never reached deep/obscure
    enough cubes to hit this) - a raw StringDataRightTruncation aborted
    the whole batch. Truncating keeps that one long value from sinking an
    otherwise-good page, matching gotcha #34's "don't let one bad field
    crash the batch" precedent.
    """
    long_name = "X" * 300  # PopularCube.name is String(256)
    long_owner = "Y" * 200  # owner_username is String(128)

    def fake_iter_all_cubes(user_agent: str, *, start_key: object = None):
        yield [
            PopularCubeEntry(
                external_id="a", short_id="a", name=long_name, owner_username=long_owner,
                source_url="https://cubecobra.com/cube/list/a", card_count=360, like_count=100, tags=None,
                num_decks=42, date_last_updated=None,
            )
        ], None

    monkeypatch.setattr(cube_discover_service.cubecobra, "iter_all_cubes", fake_iter_all_cubes)

    db = get_sessionmaker()()
    try:
        state = cube_discover_service.run_full_cube_scrape(db)
        assert state.status == "COMPLETED"

        cube = db.query(PopularCube).filter_by(external_id="a").one()
        assert len(cube.name) == 256
        assert len(cube.owner_username) == 128
    finally:
        db.close()


def test_trigger_full_scrape_rejects_concurrent_run():
    db = get_sessionmaker()()
    try:
        cube_discover_service.trigger_full_scrape(db)
        with pytest.raises(cube_discover_service.SyncAlreadyInProgressError):
            cube_discover_service.trigger_full_scrape(db)
    finally:
        db.close()


def _fetch_result(rows: list[tuple[str, int]]) -> DeckFetchResult:
    parse_result = ParseResult(
        rows=[
            ParsedRow(
                row_number=i + 1,
                raw={"name": name},
                mapped={
                    "name": name, "quantity": qty, "set_code": None, "set_name": None, "collector_number": None,
                    "language": None, "scryfall_id": None, "section": "mainboard", "category": None,
                    "tags": None, "foil": False,
                },
            )
            for i, (name, qty) in enumerate(rows)
        ]
    )
    return DeckFetchResult(deck_name=None, parse_result=parse_result)


def test_import_popular_cube_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()

        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        result = cube_discover_service.import_popular_cube(db, cube.id)

        assert result.import_error is None
        assert result.imported_list_id is not None
        assert result.import_attempted_at is not None
        imported_list = db.get(CardList, result.imported_list_id)
        assert imported_list is not None
        assert imported_list.name == cube.name
    finally:
        db.close()


def test_import_popular_cube_is_idempotent_when_already_imported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()
        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        first = cube_discover_service.import_popular_cube(db, cube.id)
        second = cube_discover_service.import_popular_cube(db, cube.id)

        assert second.imported_list_id == first.imported_list_id
        assert db.query(CardList).count() == 1  # no duplicate list created on the second call
    finally:
        db.close()


def test_import_popular_cube_cleans_up_orphaned_list_on_failure(monkeypatch: pytest.MonkeyPatch):
    """The real bug this whole feature was built around: a bulk import
    that fails after the CardList is already created must not leave an
    empty, sourceless list behind (see CLAUDE.md).
    """
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()

        def _boom(url: str, user_agent: str) -> DeckFetchResult:
            raise SourceFetchError("cubecobra unreachable")

        monkeypatch.setattr(cubecobra, "fetch_and_parse", _boom)

        result = cube_discover_service.import_popular_cube(db, cube.id)

        assert result.imported_list_id is None
        assert result.import_error is not None
        assert "cubecobra unreachable" in result.import_error
        assert db.query(CardList).count() == 0  # no orphaned list left behind
    finally:
        db.close()


def test_import_popular_cube_retry_after_failure_succeeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()

        def _boom(url: str, user_agent: str) -> DeckFetchResult:
            raise SourceFetchError("transient failure")

        monkeypatch.setattr(cubecobra, "fetch_and_parse", _boom)
        failed = cube_discover_service.import_popular_cube(db, cube.id)
        assert failed.import_error is not None

        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))
        retried = cube_discover_service.import_popular_cube(db, cube.id)

        assert retried.import_error is None
        assert retried.imported_list_id is not None
    finally:
        db.close()


def test_import_popular_cube_raises_for_unknown_cube():
    db = get_sessionmaker()()
    try:
        with pytest.raises(cube_discover_service.CubeNotFoundError):
            cube_discover_service.import_popular_cube(db, 999999)
    finally:
        db.close()


def test_import_popular_cube_adopts_existing_populated_same_name_list(monkeypatch: pytest.MonkeyPatch):
    """Real live scenario: `card_lists` has a (user_id, name) uniqueness
    constraint, and a cube already imported before this row-level tracking
    existed (e.g. the pre-fix bulk "select all") has already claimed its
    name - re-importing it must adopt that real, populated list instead of
    crashing on the constraint.
    """
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()

        pre_existing = list_service.create_list(db, name=cube.name, list_type="cube")
        from app.models.lists import CardListItem

        db.add(CardListItem(list_id=pre_existing.id, card_name="Sol Ring", quantity=1, section="mainboard"))
        db.commit()

        result = cube_discover_service.import_popular_cube(db, cube.id)

        assert result.imported_list_id == pre_existing.id
        assert result.import_error is None
        assert db.query(CardList).count() == 1  # adopted, not duplicated
    finally:
        db.close()


def test_import_popular_cube_replaces_existing_empty_same_name_list(monkeypatch: pytest.MonkeyPatch):
    """An existing same-named list with zero items is the orphaned-list
    bug itself, not a real prior import - it must be cleaned up and
    re-attempted, not adopted as a false success.
    """
    monkeypatch.setattr(cube_discover_service.cubecobra, "fetch_popular_cubes", lambda user_agent, **kw: [_entry("a")])
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube = db.query(PopularCube).filter_by(external_id="a").one()

        orphan = list_service.create_list(db, name=cube.name, list_type="cube")
        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        result = cube_discover_service.import_popular_cube(db, cube.id)

        assert result.imported_list_id is not None
        assert result.imported_list_id != orphan.id  # the empty orphan was replaced, not reused directly
        assert result.import_error is None
        assert db.query(CardList).count() == 1  # old orphan gone, one real list remains
    finally:
        db.close()


def test_import_popular_cube_does_not_cross_link_ambiguous_names(monkeypatch: pytest.MonkeyPatch):
    """Real bug found live: two distinct real cubes can share an identical
    display name (e.g. "Commander Cube" by 5 different owners). Importing
    the second one must NOT adopt the first one's real list (that would
    silently attribute one cube's content to a completely different
    cube) - it gets its own, separately named list instead.
    """
    monkeypatch.setattr(
        cube_discover_service.cubecobra,
        "fetch_popular_cubes",
        lambda user_agent, **kw: [_entry("a", name="Commander Cube"), _entry("b", name="Commander Cube")],
    )
    db = get_sessionmaker()()
    try:
        cube_discover_service.run_cube_discovery_sync(db)
        cube_a = db.query(PopularCube).filter_by(external_id="a").one()
        cube_b = db.query(PopularCube).filter_by(external_id="b").one()

        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        result_a = cube_discover_service.import_popular_cube(db, cube_a.id)
        result_b = cube_discover_service.import_popular_cube(db, cube_b.id)

        assert result_a.imported_list_id is not None
        assert result_b.imported_list_id is not None
        assert result_a.imported_list_id != result_b.imported_list_id  # two real lists, not one shared by both
        assert db.query(CardList).count() == 2

        list_a = db.get(CardList, result_a.imported_list_id)
        list_b = db.get(CardList, result_b.imported_list_id)
        assert list_a is not None and list_b is not None
        assert list_a.name != list_b.name
    finally:
        db.close()


def _seed_full_import_cube(db, **overrides: object) -> PopularCube:
    external_id = str(overrides.get("external_id", "fi-a"))
    defaults: dict[str, object] = {
        "external_id": external_id,
        "short_id": external_id,
        "name": "Full Import Cube",
        "owner_username": "Alice",
        "source_url": f"https://cubecobra.com/cube/list/{external_id}",
        "card_count": 360,
        "like_count": 0,
        "num_decks": 0,
        "owner_follower_count": None,
        "description": None,
        "tags": None,
    }
    defaults.update(overrides)
    cube = PopularCube(**defaults)
    db.add(cube)
    db.commit()
    db.refresh(cube)
    return cube


def test_full_import_candidates_excludes_small_cubes():
    db = get_sessionmaker()()
    try:
        _seed_full_import_cube(db, external_id="small", card_count=39, like_count=99999)
        big = _seed_full_import_cube(db, external_id="big", card_count=40, like_count=99999)

        ids = list(db.scalars(cube_discover_service._full_import_candidates_select()))
        assert ids == [big.id]
    finally:
        db.close()


def test_full_import_candidates_includes_top_ranked_without_description():
    """top_n=1 keeps this test meaningful with only 2 seeded rows - at the
    real top_n=10,000 default, any 2-row test DB would trivially rank both
    rows inside the top 10,000, masking the real "outside top-N" exclusion
    this test exists to verify.
    """
    db = get_sessionmaker()()
    try:
        # Distinct, clearly-ordered values on all 3 ranked dimensions so a
        # tie (e.g. both defaulting to num_decks=0) can't accidentally give
        # "unpopular" a rank-1 tie on some other axis and mask the real
        # top_n exclusion this test checks.
        popular = _seed_full_import_cube(db, external_id="popular", like_count=5000, num_decks=500, owner_follower_count=50)
        _seed_full_import_cube(db, external_id="unpopular", like_count=0, num_decks=0, owner_follower_count=0)

        ids = list(db.scalars(cube_discover_service._full_import_candidates_select(top_n=1)))
        assert ids == [popular.id]  # only the top-ranked one qualifies, no description on either
    finally:
        db.close()


def test_full_import_candidates_includes_cubes_with_description_regardless_of_rank():
    db = get_sessionmaker()()
    try:
        described = _seed_full_import_cube(
            db, external_id="described", like_count=0, num_decks=0, description="A real cube."
        )
        ids = list(db.scalars(cube_discover_service._full_import_candidates_select()))
        assert ids == [described.id]
    finally:
        db.close()


def test_full_import_candidates_includes_cubes_with_enough_followers_without_description():
    db = get_sessionmaker()()
    try:
        followed = _seed_full_import_cube(
            db, external_id="followed", like_count=0, num_decks=0, owner_follower_count=5
        )
        _seed_full_import_cube(db, external_id="unfollowed", like_count=0, num_decks=0, owner_follower_count=4)

        ids = list(db.scalars(cube_discover_service._full_import_candidates_select(top_n=0)))
        assert ids == [followed.id]  # 5 is the real, user-chosen floor - 4 doesn't qualify
    finally:
        db.close()


def test_trigger_full_import_computes_total_and_rejects_concurrent():
    db = get_sessionmaker()()
    try:
        _seed_full_import_cube(db, external_id="a", description="real")
        _seed_full_import_cube(db, external_id="b", card_count=1)  # too small, excluded

        state = cube_discover_service.trigger_full_import(db)
        assert state.status == "RUNNING"
        assert state.total_candidates == 1

        with pytest.raises(cube_discover_service.SyncAlreadyInProgressError):
            cube_discover_service.trigger_full_import(db)
    finally:
        db.close()


def test_run_full_cube_import_success_tracks_progress(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        _seed_full_import_cube(db, external_id="a", name="Cube A", description="real")
        _seed_full_import_cube(db, external_id="b", name="Cube B", description="real")
        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        state = cube_discover_service.run_full_cube_import(db)

        assert state.status == "COMPLETED"
        assert state.imported_count == 2
        assert state.failed_count == 0
        assert state.skipped_count == 0
        assert db.query(CardList).count() == 2
    finally:
        db.close()


def test_run_full_cube_import_records_failures_and_continues(monkeypatch: pytest.MonkeyPatch):
    cube_a = None

    def _fetch(url: str, user_agent: str):
        if "/a" in url:
            raise SourceFetchError("boom")
        return _fetch_result([("Sol Ring", 1)])

    db = get_sessionmaker()()
    try:
        cube_a = _seed_full_import_cube(db, external_id="a", name="Cube A", description="real")
        _seed_full_import_cube(db, external_id="b", name="Cube B", description="real")
        monkeypatch.setattr(cubecobra, "fetch_and_parse", _fetch)

        state = cube_discover_service.run_full_cube_import(db)

        assert state.status == "COMPLETED"
        assert state.imported_count == 1
        assert state.failed_count == 1
        db.refresh(cube_a)
        assert cube_a.import_error is not None
    finally:
        db.close()


def test_run_full_cube_import_skips_already_imported(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        already = _seed_full_import_cube(db, external_id="a", name="Cube A", description="real")
        real_list = list_service.create_list(db, name="Cube A", list_type="cube", user_id=DEFAULT_USER_ID)
        already.imported_list_id = real_list.id
        db.commit()
        _seed_full_import_cube(db, external_id="b", name="Cube B", description="real")
        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        state = cube_discover_service.run_full_cube_import(db)

        assert state.imported_count == 1  # only "b" was a genuinely new import
        assert state.skipped_count == 1  # "a" was already imported, not re-downloaded
    finally:
        db.close()


def test_run_full_cube_import_resumes_from_last_cube_id(monkeypatch: pytest.MonkeyPatch):
    db = get_sessionmaker()()
    try:
        cube_a = _seed_full_import_cube(db, external_id="a", name="Cube A", description="real")
        _seed_full_import_cube(db, external_id="b", name="Cube B", description="real")
        monkeypatch.setattr(cubecobra, "fetch_and_parse", lambda url, user_agent: _fetch_result([("Sol Ring", 1)]))

        state = cube_discover_service.get_full_import_state(db)
        state.last_cube_id = cube_a.id  # pretend "a" was already processed in a prior, interrupted run
        state.imported_count = 1
        db.commit()

        state = cube_discover_service.run_full_cube_import(db)

        assert state.status == "COMPLETED"
        assert state.imported_count == 2  # 1 carried over + 1 newly processed ("b" only, "a" skipped by cursor)
        cube_a_after = db.get(PopularCube, cube_a.id)
        assert cube_a_after is not None
        assert cube_a_after.imported_list_id is None  # never actually (re-)downloaded - resumed past it
    finally:
        db.close()
