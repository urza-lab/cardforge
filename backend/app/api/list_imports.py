from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.lists import ListImport
from app.parsers import LIST_PARSERS, RowValidationError
from app.schemas.lists import (
    ListImportConfirmRequest,
    ListImportPreviewResponse,
    ListImportRead,
    ListImportRowRead,
)
from app.services import list_import_service, list_service

router = APIRouter(prefix="/api/list-imports", tags=["list-imports"])


def _to_preview_response(import_record: ListImport) -> ListImportPreviewResponse:
    return ListImportPreviewResponse(
        **ListImportRead.model_validate(import_record).model_dump(),
        rows=[ListImportRowRead.model_validate(row) for row in import_record.rows],
        is_likely_duplicate=import_record.duplicate_of_import_id is not None,
    )


@router.post("/preview", response_model=ListImportPreviewResponse, status_code=201)
async def preview_import(
    file: UploadFile = File(...),
    source_type: str = Form(...),
    list_id: int = Form(...),
    db: Session = Depends(get_db),
) -> ListImportPreviewResponse:
    if source_type not in LIST_PARSERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source_type '{source_type}', expected one of {sorted(LIST_PARSERS)}",
        )

    card_list = list_service.get_list(db, list_id)
    if card_list is None:
        raise HTTPException(status_code=404, detail="list not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    try:
        import_record = list_import_service.create_preview(
            db,
            card_list=card_list,
            source_type=source_type,
            content=content,
            original_filename=file.filename,
        )
    except RowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"file is not valid UTF-8 text: {exc}") from exc

    return _to_preview_response(import_record)


@router.get("", response_model=list[ListImportRead])
def list_all_imports(list_id: int | None = None, db: Session = Depends(get_db)) -> list[ListImportRead]:
    imports = list_import_service.list_imports(db, list_id=list_id)
    return [ListImportRead.model_validate(i) for i in imports]


@router.get("/{import_id}", response_model=ListImportPreviewResponse)
def get_import(import_id: int, db: Session = Depends(get_db)) -> ListImportPreviewResponse:
    try:
        import_record = list_import_service.get_import(db, import_id)
    except list_import_service.ListImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    return _to_preview_response(import_record)


@router.post("/{import_id}/confirm", response_model=ListImportRead)
def confirm_import(
    import_id: int, payload: ListImportConfirmRequest, db: Session = Depends(get_db)
) -> ListImportRead:
    try:
        import_record = list_import_service.get_import(db, import_id)
        confirmed = list_import_service.confirm_import(
            db, import_record, skip_bad_rows=payload.skip_bad_rows
        )
    except list_import_service.ListImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    except list_import_service.ListImportNotPreviewedError as exc:
        raise HTTPException(
            status_code=409, detail=f"import is already '{exc}', cannot confirm again"
        ) from exc
    except list_import_service.ListImportHasErrorRowsError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{exc.error_row_count} row(s) failed validation; confirm with "
                "skip_bad_rows=true to import the rest, or call /abort"
            ),
        ) from exc
    return ListImportRead.model_validate(confirmed)


@router.post("/{import_id}/abort", response_model=ListImportRead)
def abort_import(import_id: int, db: Session = Depends(get_db)) -> ListImportRead:
    try:
        import_record = list_import_service.get_import(db, import_id)
        aborted = list_import_service.abort_import(db, import_record)
    except list_import_service.ListImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import not found") from exc
    except list_import_service.ListImportNotPreviewedError as exc:
        raise HTTPException(status_code=409, detail=f"import is already '{exc}', cannot abort") from exc
    return ListImportRead.model_validate(aborted)
