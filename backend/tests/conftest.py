from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.queue import get_redis
from sqlalchemy import text


def pytest_configure(config: pytest.Config) -> None:
    """Hard stop before any test can run against non-test infrastructure.

    _clean_db below unconditionally deletes from collections/imports/
    scryfall_cards — against the real `cardforge` database that means the
    user's actual collection and the ~100k-row Scryfall mirror. Only ever
    let that happen against a database whose name says it's disposable.

    Separately: tests that hit app.services.scryfall_service.trigger_sync
    enqueue a real RQ job. RQ has no concept of a "test queue" the way we
    made cardforge_test a disposable database — an enqueue lands in the same
    Redis DB index the real worker container listens on unless told
    otherwise, which means a test run could make the real worker actually
    perform a real Scryfall sync against the real database. Require a
    non-default Redis DB index too, for the same reason.
    """
    settings = get_settings()
    if "test" not in settings.postgres_db.lower():
        raise pytest.UsageError(
            f"refusing to run tests against database '{settings.postgres_db}' - it doesn't look like a "
            "test database. Set CARDFORGE_POSTGRES_DB=cardforge_test (see DEVELOPMENT.md 'Tests')."
        )
    if settings.redis_db == 0:
        raise pytest.UsageError(
            "refusing to run tests against Redis DB 0 - that's what the real worker listens on, and "
            "tests can enqueue real jobs. Set CARDFORGE_REDIS_DB=1 (see DEVELOPMENT.md 'Tests')."
        )


@pytest.fixture(autouse=True)
def _clean_db():
    """Tests run against a real Postgres (see DEVELOPMENT.md/CI) — CI uses a
    disposable `cardforge_test` database, and local runs must too (see
    DEVELOPMENT.md "Tests"): scryfall_cards holds ~100k rows of real
    reference data once synced, and a test wiping/replacing it would be
    destructive if pointed at the same DB the running app actually uses.

    Deleting collections/imports cascades to collection_items/import_rows
    (ON DELETE CASCADE); scryfall_cards is cleared and scryfall_sync_state
    reset directly since nothing cascades into them. The seeded id=1 default
    user and id=1 sync-state row are left in place.
    """
    yield
    session_local = get_sessionmaker()
    db = session_local()
    try:
        db.execute(text("DELETE FROM imports"))
        db.execute(text("DELETE FROM collections"))
        db.execute(text("DELETE FROM list_imports"))
        db.execute(text("DELETE FROM card_lists"))
        db.execute(text("DELETE FROM price_profiles"))
        db.execute(text("DELETE FROM popular_decks"))
        db.execute(text("DELETE FROM edhrec_synthesized_decks"))
        # price_observations isn't listed separately - it cascades away with
        # scryfall_cards below regardless of provider (manual/mtgjson rows
        # included), same as collection/list items' resolved_scryfall_card_id.
        db.execute(text("DELETE FROM scryfall_cards"))
        db.execute(
            text(
                "UPDATE price_sync_state SET status = 'NOT_STARTED', started_at = NULL, finished_at = NULL, "
                "price_count = 0, error_message = NULL WHERE provider = 'mtgjson'"
            )
        )
        db.execute(
            text(
                "UPDATE deck_discovery_sync_state SET status = 'NOT_STARTED', started_at = NULL, "
                "finished_at = NULL, deck_count = 0, error_message = NULL WHERE id = 1"
            )
        )
        db.execute(
            text(
                "UPDATE edhrec_sync_state SET status = 'NOT_STARTED', started_at = NULL, "
                "finished_at = NULL, deck_count = 0, error_message = NULL WHERE id = 1"
            )
        )
        db.execute(
            text(
                "UPDATE scryfall_sync_state SET status = 'NOT_STARTED', bulk_data_type = 'all_cards', "
                "source_updated_at = NULL, started_at = NULL, finished_at = NULL, card_count = 0, "
                "error_message = NULL WHERE id = 1"
            )
        )
        db.execute(
            text(
                "UPDATE user_settings SET default_comparison_mode = 'oracle', preferred_currency = 'USD', "
                "card_name_language = NULL, grafana_embed_url = NULL WHERE user_id = 1"
            )
        )
        db.commit()
    finally:
        db.close()
    # Safe unconditionally: pytest_configure already refused to start unless
    # settings.redis_db != 0, so this is always the disposable test index.
    get_redis().flushdb()
