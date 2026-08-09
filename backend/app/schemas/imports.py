from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    raw_data: dict[str, Any]
    mapped_data: dict[str, Any] | None
    status: str
    error_reason: str | None


class ImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    collection_id: int
    source_type: str
    original_filename: str | None
    status: str
    column_mapping: dict[str, Any] | None
    total_rows: int
    valid_rows: int
    error_rows: int
    imported_rows: int
    duplicate_of_import_id: int | None
    created_at: datetime
    confirmed_at: datetime | None


class ImportPreviewResponse(ImportRead):
    rows: list[ImportRowRead]
    # True when a *confirmed* import with the same file content hash already
    # exists for this collection (IMPORT_FORMATS.md "Duplicate import
    # prevention") — surfaced so the UI can warn before the user confirms.
    is_likely_duplicate: bool


class ImportConfirmRequest(BaseModel):
    skip_bad_rows: bool = False
