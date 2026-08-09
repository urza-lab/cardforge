from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.database import get_sessionmaker


@pytest.fixture(autouse=True)
def _clean_db():
    """Import/collection tests hit the real Postgres configured via env (same
    DB the app itself would use — see DEVELOPMENT.md/CI). Deleting collections
    and imports after each test cascades to collection_items/import_rows
    (ON DELETE CASCADE) and leaves the seeded id=1 default user untouched.
    """
    yield
    session_local = get_sessionmaker()
    db = session_local()
    try:
        db.execute(text("DELETE FROM imports"))
        db.execute(text("DELETE FROM collections"))
        db.commit()
    finally:
        db.close()
