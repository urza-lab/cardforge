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


def main() -> None:
    configure_logging()
    log = logging.getLogger("cardforge.worker")
    settings = get_settings()

    conn = Redis.from_url(settings.redis_url())
    conn.ping()  # fail fast and loudly if Redis is not reachable
    log.info("connected to redis at %s, listening on queues: %s", settings.redis_url(), QUEUE_NAMES)

    threading.Thread(target=_staleness_sweep_loop, args=(conn,), daemon=True).start()

    queues = [Queue(name, connection=conn) for name in QUEUE_NAMES]
    worker = Worker(queues, connection=conn, name="cardforge-worker")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
