"""RQ queue connection factory — mirrors app.core.database's lazy
engine/session singletons, but for enqueuing background jobs (app/workers/)
instead of DB access.
"""
from __future__ import annotations

from redis import Redis
from rq import Queue

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url())
    return _redis


def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=get_redis())
