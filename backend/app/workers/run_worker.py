"""CardForge background worker entrypoint.

Runs an RQ worker against Redis, processing the job queues used by the
refresh system (Phase 5) and the price refresh queue (Phase 6):
`refresh` (source/list refresh jobs) and `pricing` (price lookups), plus the
default queue for one-off jobs such as the initial Scryfall bulk import.

This is a real, functioning worker process from Phase 1 onward — it connects
to Redis and blocks waiting for jobs. Phases 5/6 add the job functions it
executes; there is no placeholder job that reports fake success.

The staleness sweep (Phase 5) that periodically re-enqueues URL-sourced list
refreshes is a plain daemon thread here, not RQ's own scheduler
(`with_scheduler=True` only covers one-off `enqueue_at`/`enqueue_in` calls —
installed rq==2.1.0 has no repeating/cron job support, see ARCHITECTURE.md
"Documented default decisions"). A thread inside this single worker process
is enough for a self-hosted single/few-user tool and avoids the trouble of
a self-perpetuating enqueue_at chain surviving worker restarts cleanly.
"""
from __future__ import annotations

import logging
import threading
import time

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging

QUEUE_NAMES = ["default", "refresh", "pricing"]

# How often the staleness sweep runs. Lists go stale after 7 days (see
# app.services.list_refresh_service.STALE_AFTER) - checking every few hours
# is cheap (one query, no external HTTP) and plenty timely against that.
STALENESS_SWEEP_INTERVAL_SECONDS = 6 * 60 * 60
STALENESS_SWEEP_STARTUP_DELAY_SECONDS = 60

# Same startup grace period as the staleness sweep - let the worker (and its
# DB connection pool) finish booting before this thread's first tick.
PERIODIC_SYNC_STARTUP_DELAY_SECONDS = 60


def _staleness_sweep_loop(conn: Redis) -> None:
    log = logging.getLogger("cardforge.worker.staleness_sweep")
    from app.workers.jobs import check_stale_lists

    queue = Queue("refresh", connection=conn)
    time.sleep(STALENESS_SWEEP_STARTUP_DELAY_SECONDS)  # let the worker finish booting first
    while True:
        try:
            queue.enqueue(check_stale_lists)
        except Exception:
            log.exception("failed to enqueue staleness sweep job")
        time.sleep(STALENESS_SWEEP_INTERVAL_SECONDS)


def _periodic_data_sync_loop(interval_seconds: int) -> None:
    """Keeps the Scryfall card mirror and MTGJSON price cache from going
    stale without a manual "Sync now" click - user-requested. Same plain
    daemon-thread-with-a-sleep-loop shape as the staleness sweep above (same
    reasoning: rq==2.1.0 has no repeating/cron job support, see
    ARCHITECTURE.md "Documented default decisions").

    Reuses each provider's own trigger_sync (app.services.scryfall_service /
    mtgjson_service) rather than enqueueing the sync job directly - that's
    the same function the "Sync now" button calls, so a tick that lands
    while a sync is already FETCHING (started manually, or by the other
    provider's tick, or a slow previous run) is rejected the same way a
    second manual click would be, instead of queueing a wasteful duplicate.
    """
    log = logging.getLogger("cardforge.worker.periodic_data_sync")
    from app.core.database import get_sessionmaker
    from app.services import mtgjson_service, scryfall_service

    session_local = get_sessionmaker()
    time.sleep(PERIODIC_SYNC_STARTUP_DELAY_SECONDS)
    while True:
        for name, trigger in (("scryfall", scryfall_service.trigger_sync), ("mtgjson", mtgjson_service.trigger_sync)):
            db = session_local()
            try:
                trigger(db)
                log.info("periodic %s sync enqueued", name)
            except (scryfall_service.SyncAlreadyInProgressError, mtgjson_service.SyncAlreadyInProgressError):
                log.info("periodic %s sync skipped - a sync is already in progress", name)
            except Exception:
                log.exception("periodic %s sync tick failed", name)
            finally:
                db.close()
        time.sleep(interval_seconds)


def main() -> None:
    configure_logging()
    log = logging.getLogger("cardforge.worker")
    settings = get_settings()

    conn = Redis.from_url(settings.redis_url())
    conn.ping()  # fail fast and loudly if Redis is not reachable
    log.info("connected to redis at %s, listening on queues: %s", settings.redis_url(), QUEUE_NAMES)

    threading.Thread(target=_staleness_sweep_loop, args=(conn,), daemon=True).start()

    if settings.periodic_sync_enabled:
        interval_seconds = settings.periodic_sync_interval_hours * 60 * 60
        threading.Thread(target=_periodic_data_sync_loop, args=(interval_seconds,), daemon=True).start()
        log.info("periodic Scryfall/MTGJSON sync enabled, every %dh", settings.periodic_sync_interval_hours)
    else:
        log.info("periodic Scryfall/MTGJSON sync disabled (CARDFORGE_PERIODIC_SYNC_ENABLED=false)")

    queues = [Queue(name, connection=conn) for name in QUEUE_NAMES]
    worker = Worker(queues, connection=conn, name="cardforge-worker")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
