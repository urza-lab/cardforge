"""Import orchestration: parse -> persist preview -> confirm/abort.

See IMPORT_FORMATS.md for the pipeline this implements: file check -> preview
(with per-row validation) -> explicit confirm (skip-bad-rows or not) or
abort. Nothing lands in `collection_items` until `confirm_import` runs, and
`confirm_import` refuses to run at all if there are error rows unless the
caller explicitly opts into skipping them.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionItem
from app.models.imports import Import, ImportRow, ImportRowStatus, ImportStatus
from app.models.user import DEFAULT_USER_ID
from app.parsers import PARSERS
from app.services import scryfall_resolution


class ImportNotFoundError(Exception):
    pass


class ImportNotPreviewedError(Exception):
    """Confirm/abort was attempted on an import no longer in 'previewed' state."""


class ImportHasErrorRowsError(Exception):
    """confirm_import() was called with error rows present and skip_bad_rows=False."""

    def __init__(self, error_row_count: int):
        self.error_row_count = error_row_count
        super().__init__(str(error_row_count))


def hash_file(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_prior_confirmed_import(db: Session, collection_id: int, file_hash: str) -> Import | None:
    stmt = (
        select(Import)
        .where(
            Import.collection_id == collection_id,
            Import.file_hash == file_hash,
            Import.status.in_([ImportStatus.confirmed.value, ImportStatus.partially_confirmed.value]),
        )
        .order_by(Import.created_at.desc())
    )
    return db.scalars(stmt).first()


def create_preview(
    db: Session,
    *,
    collection: Collection,
    source_type: str,
    content: bytes,
    original_filename: str | None,
    column_mapping: dict[str, str] | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> Import:
    if source_type not in PARSERS:
        raise ValueError(f"unknown source_type '{source_type}', expected one of {sorted(PARSERS)}")

    parser = PARSERS[source_type]
    text = content.decode("utf-8-sig")  # tolerate a BOM from Excel-exported CSVs
    kwargs: dict[str, Any] = {"column_mapping": column_mapping} if source_type == "generic_csv" else {}
    # A RowValidationError raised here (not caught per-row) is a file-level
    # problem (missing required column, unparseable JSON) — it propagates to
    # the caller, which turns it into a 422 before anything is persisted.
    parse_result = parser(text, **kwargs)

    file_hash = hash_file(content)
    duplicate = find_prior_confirmed_import(db, collection.id, file_hash)

    import_record = Import(
        user_id=user_id,
        collection_id=collection.id,
        source_type=source_type,
        original_filename=original_filename,
        file_hash=file_hash,
        status=ImportStatus.previewed.value,
        column_mapping=parse_result.detected_columns,
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
            ImportRow(
                import_id=import_record.id,
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
    db: Session, *, collection_id: int | None = None, user_id: int = DEFAULT_USER_ID
) -> list[Import]:
    stmt = select(Import).where(Import.user_id == user_id)
    if collection_id is not None:
        stmt = stmt.where(Import.collection_id == collection_id)
    stmt = stmt.order_by(Import.created_at.desc())
    return list(db.scalars(stmt))


def get_import(db: Session, import_id: int, user_id: int = DEFAULT_USER_ID) -> Import:
    stmt = select(Import).where(Import.id == import_id, Import.user_id == user_id)
    import_record = db.scalars(stmt).first()
    if import_record is None:
        raise ImportNotFoundError(import_id)
    return import_record


def confirm_import(db: Session, import_record: Import, *, skip_bad_rows: bool) -> Import:
    if import_record.status != ImportStatus.previewed.value:
        raise ImportNotPreviewedError(import_record.status)
    if import_record.error_rows and not skip_bad_rows:
        raise ImportHasErrorRowsError(import_record.error_rows)

    rows_to_commit = [row for row in import_record.rows if row.status == ImportRowStatus.ok.value]
    new_items: list[CollectionItem] = []
    for row in rows_to_commit:
        mapped = row.mapped_data
        assert mapped is not None  # ok rows always have mapped_data (see parsers/common.py)
        item = CollectionItem(
            collection_id=import_record.collection_id,
            card_name=mapped["name"],
            set_code=mapped["set_code"],
            set_name=mapped["set_name"],
            collector_number=mapped["collector_number"],
            quantity=mapped["quantity"],
            foil=mapped["foil"],
            language=mapped["language"],
            condition=mapped["condition"],
            purchase_price=Decimal(mapped["purchase_price"]) if mapped["purchase_price"] else None,
            purchase_currency=mapped["purchase_currency"],
            scryfall_id=mapped["scryfall_id"],
            source_import_id=import_record.id,
        )
        db.add(item)
        new_items.append(item)

    # Resolve against the local Scryfall mirror immediately (Phase 3) so
    # freshly-imported cards are comparison-ready without a separate manual
    # step. If nothing has been synced yet (scryfall_cards empty), every item
    # just resolves to "unresolved" here and picks up real matches the next
    # time someone re-resolves the collection after a sync.
    for item in new_items:
        scryfall_resolution.resolve_item(db, item)

    import_record.imported_rows = len(rows_to_commit)
    import_record.status = (
        ImportStatus.confirmed.value
        if import_record.error_rows == 0
        else ImportStatus.partially_confirmed.value
    )
    import_record.confirmed_at = datetime.now(UTC)
    db.commit()
    db.refresh(import_record)
    return import_record


def abort_import(db: Session, import_record: Import) -> Import:
    if import_record.status != ImportStatus.previewed.value:
        raise ImportNotPreviewedError(import_record.status)
    import_record.status = ImportStatus.aborted.value
    db.commit()
    db.refresh(import_record)
    return import_record
