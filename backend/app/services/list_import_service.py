"""List (deck/cube) import orchestration: parse -> persist preview ->
confirm/abort. Mirrors app/services/import_service.py (Phase 2's collection
import pipeline) but targets CardList/CardListItem — see app/models/lists.py
for why this isn't generalized into one shared pipeline.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lists import (
    CardList,
    CardListItem,
    ListImport,
    ListImportRow,
    ListImportRowStatus,
    ListImportStatus,
)
from app.models.user import DEFAULT_USER_ID
from app.parsers import LIST_PARSERS
from app.services import scryfall_resolution


class ListImportNotFoundError(Exception):
    pass


class ListImportNotPreviewedError(Exception):
    """Confirm/abort was attempted on a list import no longer 'previewed'."""


class ListImportHasErrorRowsError(Exception):
    """confirm_import() was called with error rows present and skip_bad_rows=False."""

    def __init__(self, error_row_count: int):
        self.error_row_count = error_row_count
        super().__init__(str(error_row_count))


def hash_file(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_prior_confirmed_import(db: Session, list_id: int, file_hash: str) -> ListImport | None:
    stmt = (
        select(ListImport)
        .where(
            ListImport.list_id == list_id,
            ListImport.file_hash == file_hash,
            ListImport.status.in_(
                [ListImportStatus.confirmed.value, ListImportStatus.partially_confirmed.value]
            ),
        )
        .order_by(ListImport.created_at.desc())
    )
    return db.scalars(stmt).first()


def create_preview(
    db: Session,
    *,
    card_list: CardList,
    source_type: str,
    content: bytes,
    original_filename: str | None,
    user_id: int = DEFAULT_USER_ID,
) -> ListImport:
    if source_type not in LIST_PARSERS:
        raise ValueError(f"unknown source_type '{source_type}', expected one of {sorted(LIST_PARSERS)}")

    parser = LIST_PARSERS[source_type]
    text = content.decode("utf-8-sig")  # tolerate a BOM from Excel-exported files
    parse_result = parser(text)

    file_hash = hash_file(content)
    duplicate = find_prior_confirmed_import(db, card_list.id, file_hash)

    import_record = ListImport(
        user_id=user_id,
        list_id=card_list.id,
        source_type=source_type,
        original_filename=original_filename,
        file_hash=file_hash,
        status=ListImportStatus.previewed.value,
        total_rows=len(parse_result.rows),
        valid_rows=len(parse_result.valid_rows),
        error_rows=len(parse_result.error_rows),
        imported_rows=0,
        duplicate_of_import_id=duplicate.id if duplicate else None,
    )
    db.add(import_record)
    db.flush()  # assigns import_record.id, needed for the rows' FK below

    for row in parse_result.rows:
        db.add(
            ListImportRow(
                list_import_id=import_record.id,
                row_number=row.row_number,
                raw_data=row.raw,
                mapped_data=row.mapped,
                status=row.status,
                error_reason=row.error,
            )
        )

    db.commit()
    db.refresh(import_record)
    return import_record


def list_imports(
    db: Session, *, list_id: int | None = None, user_id: int = DEFAULT_USER_ID
) -> list[ListImport]:
    stmt = select(ListImport).where(ListImport.user_id == user_id)
    if list_id is not None:
        stmt = stmt.where(ListImport.list_id == list_id)
    stmt = stmt.order_by(ListImport.created_at.desc())
    return list(db.scalars(stmt))


def get_import(db: Session, import_id: int, user_id: int = DEFAULT_USER_ID) -> ListImport:
    stmt = select(ListImport).where(ListImport.id == import_id, ListImport.user_id == user_id)
    import_record = db.scalars(stmt).first()
    if import_record is None:
        raise ListImportNotFoundError(import_id)
    return import_record


def confirm_import(db: Session, import_record: ListImport, *, skip_bad_rows: bool) -> ListImport:
    if import_record.status != ListImportStatus.previewed.value:
        raise ListImportNotPreviewedError(import_record.status)
    if import_record.error_rows and not skip_bad_rows:
        raise ListImportHasErrorRowsError(import_record.error_rows)

    rows_to_commit = [row for row in import_record.rows if row.status == ListImportRowStatus.ok.value]
    new_items: list[CardListItem] = []
    for row in rows_to_commit:
        mapped = row.mapped_data
        assert mapped is not None  # ok rows always have mapped_data (see parsers/common.py)
        item = CardListItem(
            list_id=import_record.list_id,
            card_name=mapped["name"],
            set_code=mapped["set_code"],
            set_name=mapped["set_name"],
            collector_number=mapped["collector_number"],
            quantity=mapped["quantity"],
            section=mapped.get("section") or "mainboard",
            category=mapped.get("category"),
            tags=mapped.get("tags"),
            foil=mapped["foil"],
            language=mapped["language"],
            scryfall_id=mapped["scryfall_id"],
            source_import_id=import_record.id,
        )
        db.add(item)
        new_items.append(item)

    # Resolve against the local Scryfall mirror immediately, same as
    # collection import (Phase 3) — see scryfall_resolution.ResolvableItem.
    for item in new_items:
        scryfall_resolution.resolve_item(db, item)

    import_record.imported_rows = len(rows_to_commit)
    import_record.status = (
        ListImportStatus.confirmed.value
        if import_record.error_rows == 0
        else ListImportStatus.partially_confirmed.value
    )
    import_record.confirmed_at = datetime.now(UTC)
    db.commit()
    db.refresh(import_record)
    return import_record


def abort_import(db: Session, import_record: ListImport) -> ListImport:
    if import_record.status != ListImportStatus.previewed.value:
        raise ListImportNotPreviewedError(import_record.status)
    import_record.status = ListImportStatus.aborted.value
    db.commit()
    db.refresh(import_record)
    return import_record
