from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.cubecobra import (
    CubeDiscoverySyncStatusRead,
    CubeFullImportStatusRead,
    CubeFullImportTriggerRequest,
    CubeFullScrapeStatusRead,
    PopularCubeRead,
)
from app.services import cube_discover_service

router = APIRouter(prefix="/api/cube-discover", tags=["cube-discover"])

# A module-level singleton, not a fresh call in the endpoint's own default
# (ruff B008) - immutable in practice (this endpoint only ever reads its
# fields), so sharing one instance across requests is safe.
_DEFAULT_FULL_IMPORT_TRIGGER = CubeFullImportTriggerRequest()


@router.get("/cubes", response_model=list[PopularCubeRead])
def list_popular_cubes(
    sort: str = "likes",
    has_description: bool | None = None,
    featured: bool | None = None,
    min_followers: int | None = None,
    min_card_count: int | None = None,
    max_card_count: int | None = None,
    limit: int = cube_discover_service.DEFAULT_LIST_LIMIT,
    db: Session = Depends(get_db),
) -> list[PopularCubeRead]:
    cubes = cube_discover_service.list_popular_cubes(
        db,
        sort=sort,
        has_description=has_description,
        featured=featured,
        min_followers=min_followers,
        min_card_count=min_card_count,
        max_card_count=max_card_count,
        limit=limit,
    )
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


@router.get("/cubes/full-scrape/status", response_model=CubeFullScrapeStatusRead)
def get_full_scrape_status(db: Session = Depends(get_db)) -> CubeFullScrapeStatusRead:
    return CubeFullScrapeStatusRead.model_validate(cube_discover_service.get_full_scrape_state(db))


@router.post("/cubes/full-scrape", response_model=CubeFullScrapeStatusRead, status_code=202)
def trigger_full_scrape(db: Session = Depends(get_db)) -> CubeFullScrapeStatusRead:
    """User-requested: a real, unbounded walk of CubeCobra's full catalog
    (not just the top-N-by-popularity the regular sync above covers) - see
    cube_discover_service.run_full_cube_scrape for why this can take an
    unknown, potentially very long time and reports live progress instead
    of an ETA.
    """
    try:
        state = cube_discover_service.trigger_full_scrape(db)
    except cube_discover_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a full cube scrape is already in progress") from exc
    return CubeFullScrapeStatusRead.model_validate(state)


@router.get("/cubes/full-import/status", response_model=CubeFullImportStatusRead)
def get_full_import_status(db: Session = Depends(get_db)) -> CubeFullImportStatusRead:
    return CubeFullImportStatusRead.model_validate(cube_discover_service.get_full_import_state(db))


@router.post("/cubes/full-import", response_model=CubeFullImportStatusRead, status_code=202)
def trigger_full_import(
    body: CubeFullImportTriggerRequest = _DEFAULT_FULL_IMPORT_TRIGGER,
    db: Session = Depends(get_db),
) -> CubeFullImportStatusRead:
    """User-requested: a real, resumable bulk *import* (download + create a
    CardList) over a filtered subset of the cached cube pool - see
    cube_discover_service.run_full_cube_import for the candidate rule and
    why this is safe to call again after an interruption (resumes from
    `last_cube_id` instead of restarting or re-downloading). `body`'s
    filters (user-requested, 2026-08-21) are stored on the state row for
    this call and every resume afterward - see trigger_full_import's own
    docstring.
    """
    try:
        state = cube_discover_service.trigger_full_import(
            db,
            min_card_count=body.min_card_count,
            max_card_count=body.max_card_count,
            require_description=body.require_description,
            top_n=body.top_n,
            max_total=body.max_total,
        )
    except cube_discover_service.SyncAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail="a full cube import is already in progress") from exc
    return CubeFullImportStatusRead.model_validate(state)


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
