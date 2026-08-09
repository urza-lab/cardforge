from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.user import User


class ImportSourceType(str, enum.Enum):
    manabox_csv = "manabox_csv"
    generic_csv = "generic_csv"
    text_list = "text_list"
    json = "json"


class ImportStatus(str, enum.Enum):
    previewed = "previewed"
    confirmed = "confirmed"
    partially_confirmed = "partially_confirmed"
    aborted = "aborted"


class ImportRowStatus(str, enum.Enum):
    ok = "ok"
    error = "error"


# Enum columns are stored as plain VARCHAR (native_enum=False, i.e. just
# String here) rather than Postgres native ENUM types: native enums need an
# `ALTER TYPE ... ADD VALUE` migration every time a status/source value is
# added, which can't run inside a transaction in older Postgres and is easy
# to forget. A CHECK-free VARCHAR validated at the Pydantic/service layer
# keeps adding a new source type or status a pure application-code change.


class Import(Base):
    """One upload attempt: preview → confirm/abort, per IMPORT_FORMATS.md.

    Rows are persisted (see ImportRow) as soon as the file is parsed, *before*
    confirmation, so the preview step is a real, re-fetchable resource and the
    confirm step is just "commit the rows already on this record" — nothing
    about the parse has to be held in server memory or re-sent by the client.
    """

    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(String(256))
    # sha256 hex digest of the uploaded file bytes, used for duplicate-upload
    # detection (IMPORT_FORMATS.md "Duplicate import prevention"). Not unique
    # at the DB level: re-uploading the same file is allowed, just flagged.
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ImportStatus.previewed.value)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_of_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column()

    user: Mapped[User] = relationship(back_populates="imports")
    collection: Mapped[Collection] = relationship(back_populates="imports")
    rows: Mapped[list[ImportRow]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
        order_by="ImportRow.row_number",
    )


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    mapped_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    error_reason: Mapped[str | None] = mapped_column(String(512))

    import_record: Mapped[Import] = relationship(back_populates="rows")
