from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.imports import Import
from app.parsers import PARSERS, RowValidationError
from app.schemas.imports import ImportConfirmRequest, ImportPreviewResponse, ImportRead, ImportRowRead
from app.services import collection_service, import_service

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _to_preview_response(import_record: Import) -> ImportPreviewResponse:
    return ImportPreviewResponse(
        **ImportRead.model_validate(import_record).model_dump(),
        rows=[ImportRowRead.model_validate(row) for row in import_record.rows],
        is_likely_duplicate=import_record.duplicate_of_import_id is not None,
    )


@router.post("/preview", response_model=ImportPreviewResponse, status_code=201)
async def preview_import(
    file: UploadFile = File(...),
    source_type: str = Form(...),
    collection_id: int = Form(...),
    # JSON-encoded {canonical_field: source_header}; generic_csv only, lets
    # the UI override auto-detected columns instead of re-uploading.
    column_mapping: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ImportPreviewResponse:
    if source_type not in PARSERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source_type '{source_type}', expected one of {sorted(PARSERS)}",
        )

    collection = collection_service.get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    mapping_dict: dict[str, str] | None = None
    if column_mapping:
        try:
            mapping_dict = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"column_mapping is not valid JSON: {exc}") from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    try:
        import_record = import_service.create_preview(
            db,
            collection=collection,
            source_type=source_type,
            content=content,
            original_filename=file.filename,
            column_mapping=mapping_dict,
        )
    except RowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"file is not valid UTF-8 text: {exc}") from exc

    return _to_preview_response(import_record)


@router.get("", response_model=list[ImportRead])
def list_imports(collection_id: int | None = None, db: Session = Depends(get_db)) -> list[ImportRead]:
    imports = import_service.list_imports(db, collection_id=collection_id)
    return [ImportRead.model_validate(i) for i in imports]


@router.get("/{import_id}", response_model=ImportPreviewResponse)
def get_import(import_id: int, db: Session = Depends(get_db)) -> ImportPreviewResponse:
    try:
        import_record = import_service.get_import(db, import_id)
    except import_service.ImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    return _to_preview_response(import_record)


@router.post("/{import_id}/confirm", response_model=ImportRead)
def confirm_import(
    import_id: int, payload: ImportConfirmRequest, db: Session = Depends(get_db)
) -> ImportRead:
    try:
        import_record = import_service.get_import(db, import_id)
        confirmed = import_service.confirm_import(db, import_record, skip_bad_rows=payload.skip_bad_rows)
    except import_service.ImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    except import_service.ImportNotPreviewedError as exc:
        raise HTTPException(
            status_code=409, detail=f"import is already '{exc}', cannot confirm again"
        ) from exc
    except import_service.ImportHasErrorRowsError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{exc.error_row_count} row(s) failed validation; confirm with "
                "skip_bad_rows=true to import the rest, or call /abort"
            ),
        ) from exc
    return ImportRead.model_validate(confirmed)


@router.post("/{import_id}/abort", response_model=ImportRead)
def abort_import(import_id: int, db: Session = Depends(get_db)) -> ImportRead:
    try:
        import_record = import_service.get_import(db, import_id)
        aborted = import_service.abort_import(db, import_record)
    except import_service.ImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    except import_service.ImportNotPreviewedError as exc:
        raise HTTPException(status_code=409, detail=f"import is already '{exc}', cannot abort") from exc
    return ImportRead.model_validate(aborted)
