from __future__ import annotations

import pytest
from app.core.database import get_sessionmaker
from app.models.cubecobra import CUBE_DISCOVERY_SYNC_STATE_ID, CubeDiscoverySyncState, PopularCube
from app.services import cube_discover_service
from app.source_adapters.cubecobra import PopularCubeEntry
from app.source_adapters.errors import SourceFetchError


def _entry(external_id: str) -> PopularCubeEntry:
    return PopularCubeEntry(
        external_id=external_id, short_id=external_id, name=f"Cube {external_id}", owner_username="Alice",
        source_url=f"https://cubecobra.com/cube/list/{external_id}", card_count=360, like_count=100, tags=None,
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
