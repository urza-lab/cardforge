"""CardForge background worker entrypoint.

Runs an RQ worker against Redis, processing the job queues used by the
refresh system (Phase 5) and the price refresh queue (Phase 6):
`refresh` (source/list refresh jobs) and `pricing` (price lookups), plus the
default queue for one-off jobs such as the initial Scryfall bulk import.

This is a real, functioning worker process from Phase 1 onward — it connects
to Redis and blocks waiting for jobs. Phases 5/6 add the job functions it
executes; there is no placeholder job that reports fake success.
"""
from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging

QUEUE_NAMES = ["default", "refresh", "pricing"]


def main() -> None:
    configure_logging()
    log = logging.getLogger("cardforge.worker")
    settings = get_settings()

    conn = Redis.from_url(settings.redis_url())
    conn.ping()  # fail fast and loudly if Redis is not reachable
    log.info("connected to redis at %s, listening on queues: %s", settings.redis_url(), QUEUE_NAMES)

    queues = [Queue(name, connection=conn) for name in QUEUE_NAMES]
    worker = Worker(queues, connection=conn, name="cardforge-worker")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
