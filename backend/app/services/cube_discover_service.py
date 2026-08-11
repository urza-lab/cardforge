"""Popular-cube discovery: sync orchestration (mirrors
app/services/discover_service.py's FETCHING/CURRENT/FAILED shape) plus the
read-side query the browse API uses. See app/source_adapters/cubecobra.py
for the actual sync work and app/models/cubecobra.py for why this is a
separate cache from `PopularDeck`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.queue import get_queue
from app.models.cubecobra import (
    CUBE_DISCOVERY_SYNC_STATE_ID,
    CubeDiscoverySyncState,
    CubeDiscoverySyncStatus,
    PopularCube,
)
from app.source_adapters import cubecobra


class SyncAlreadyInProgressError(Exception):
    pass


def get_sync_state(db: Session) -> CubeDiscoverySyncState:
    state = db.get(CubeDiscoverySyncState, CUBE_DISCOVERY_SYNC_STATE_ID)
    if state is None:
        raise RuntimeError("cube_discovery_sync_state row is missing - has the migration been applied?")
    return state


def trigger_sync(db: Session) -> CubeDiscoverySyncState:
    state = get_sync_state(db)
    if state.status == CubeDiscoverySyncStatus.fetching.value:
        raise SyncAlreadyInProgressError

    # Imported here, not at module load - same lazy-import reasoning as
    # discover_service.trigger_sync (avoids a hard API->worker import cycle).
    from app.workers.jobs import sync_popular_cubes

    get_queue("default").enqueue(sync_popular_cubes, job_timeout=600)
    state.status = CubeDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()
    db.refresh(state)
    return state


def run_cube_discovery_sync(db: Session, settings: Settings | None = None) -> CubeDiscoverySyncState:
    settings = settings or get_settings()
    state = get_sync_state(db)

    state.status = CubeDiscoverySyncStatus.fetching.value
    state.started_at = datetime.now(UTC)
    state.error_message = None
    db.commit()

    try:
        cubes = cubecobra.fetch_popular_cubes(settings.scryfall_user_agent)

        db.execute(delete(PopularCube))
        if cubes:
            db.execute(
                insert(PopularCube),
                [
                    {
                        "external_id": c.external_id,
                        "short_id": c.short_id,
                        "name": c.name,
                        "owner_username": c.owner_username,
                        "source_url": c.source_url,
                        "card_count": c.card_count,
                        "like_count": c.like_count,
                        "tags": c.tags,
                    }
                    for c in cubes
                ],
            )

        state.status = CubeDiscoverySyncStatus.current.value
        state.cube_count = len(cubes)
        state.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not silently swallowed
        db.rollback()
        state = get_sync_state(db)
        state.status = CubeDiscoverySyncStatus.failed.value
        state.error_message = str(exc)[:1024]
        state.finished_at = datetime.now(UTC)
        db.commit()
        raise

    return state


def list_popular_cubes(db: Session, *, sort: str = "likes") -> list[PopularCube]:
    order_column = PopularCube.card_count if sort == "cards" else PopularCube.like_count
    stmt = select(PopularCube).order_by(order_column.desc())
    return list(db.scalars(stmt))
