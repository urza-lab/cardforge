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
