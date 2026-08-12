from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.cubecobra import CubeDiscoverySyncStatusRead, PopularCubeRead
from app.services import cube_discover_service

router = APIRouter(prefix="/api/cube-discover", tags=["cube-discover"])


@router.get("/cubes", response_model=list[PopularCubeRead])
def list_popular_cubes(sort: str = "likes", db: Session = Depends(get_db)) -> list[PopularCubeRead]:
    cubes = cube_discover_service.list_popular_cubes(db, sort=sort)
    return [PopularCubeRead.model_validate(c) for c in cubes]


@router.get("/cubes/status", response_model=CubeDiscoverySyncStatusRead)
def get_sync_status(db: Session = Depends(get_db)) -> CubeDiscoverySyncStatusRead:
    return CubeDiscoverySyncStatusRead.model_validate(cube_discover_service.get_sync_state(db))


@router.post("/cubes/sync", response_model=CubeDiscoverySyncStatusRead, status_code=202)
def trigger_sync(db: Session = Depends(get_db)) -> CubeDiscoverySyncStatusRead:
    try:
        state = cube_discover_service.trigger_sync(db)
    except cube_discover_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a cube discovery sync is already in progress") from exc
    return CubeDiscoverySyncStatusRead.model_validate(state)


@router.post("/cubes/{cube_id}/import", response_model=PopularCubeRead)
def import_popular_cube(cube_id: int, db: Session = Depends(get_db)) -> PopularCubeRead:
    """Synchronous on-demand/retry import (user-requested) - see
    cube_discover_service.import_popular_cube for why a failed import
    comes back as a normal 200 response with `import_error` set, not an
    HTTP error: it's a real, retryable, trackable outcome, not a server
    fault. Only a genuinely missing cube raises.
    """
    try:
        cube = cube_discover_service.import_popular_cube(db, cube_id)
    except cube_discover_service.CubeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="popular cube not found") from exc
    return PopularCubeRead.model_validate(cube)
