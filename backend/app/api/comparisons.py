from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.parsers import RowValidationError
from app.schemas.comparison import ComparisonResponse, ComparisonRowErrorRead, MissingCardRead
from app.services import collection_service, comparison_service

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


@router.post("/run", response_model=ComparisonResponse)
async def run_comparison(
    collection_id: int = Form(...),
    source_type: str = Form(...),
    mode: str = Form("oracle"),
    # A decklist is small enough to paste directly - `text` covers that; `file`
    # is there for json/generic_csv (or a longer text list) uploaded as a file.
    # Exactly one of the two must be given.
    text: str | None = Form(default=None),
    column_mapping: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> ComparisonResponse:
    collection = collection_service.get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    if text is not None and text.strip():
        content = text
    elif file is not None:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="uploaded file is empty")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"file is not valid UTF-8 text: {exc}") from exc
    else:
        raise HTTPException(status_code=400, detail="provide either 'text' or a 'file'")

    mapping_dict: dict[str, str] | None = None
    if column_mapping:
        try:
            mapping_dict = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"column_mapping is not valid JSON: {exc}") from exc

    try:
        run = comparison_service.run_comparison(
            db,
            collection_id=collection_id,
            source_type=source_type,
            content=content,
            mode=mode,
            column_mapping=mapping_dict,
        )
    except comparison_service.UnsupportedSourceTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except comparison_service.InvalidComparisonModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ComparisonResponse(
        mode=run.result.mode,
        total_required_cards=run.result.total_required_cards,
        total_required_quantity=run.result.total_required_quantity,
        total_owned_quantity=run.result.total_owned_quantity,
        coverage_percent=run.result.coverage_percent,
        is_fully_buildable=run.result.is_fully_buildable,
        missing=[
            MissingCardRead(
                name=m.name,
                oracle_id=m.oracle_id,
                required_quantity=m.required_quantity,
                owned_quantity=m.owned_quantity,
                missing_quantity=m.missing_quantity,
            )
            for m in run.result.missing
        ],
        row_errors=[
            ComparisonRowErrorRead(row_number=e.row_number, raw=e.raw, error=e.error) for e in run.row_errors
        ],
    )
