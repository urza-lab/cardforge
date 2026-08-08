"""Health endpoints.

- /api/health/live  -> liveness: process is up, always 200 once FastAPI is serving.
- /api/health/ready -> readiness: verifies Postgres and Redis are actually reachable.
  Used by Docker healthchecks and the frontend "system status" page.
"""
from __future__ import annotations

import time

import redis
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.secrets import SecretNotAvailableError

router = APIRouter(prefix="/api/health", tags=["health"])

_START_TIME = time.time()


@router.get("/live")
def liveness() -> dict:
    return {"status": "ok", "uptime_seconds": round(time.time() - _START_TIME, 1)}


@router.get("/ready")
def readiness() -> dict:
    settings = get_settings()
    checks: dict[str, dict] = {}
    overall_ok = True

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = {"ok": True}
    except SecretNotAvailableError as exc:
        checks["postgres"] = {"ok": False, "error": str(exc)}
        overall_ok = False
    except Exception as exc:  # noqa: BLE001 - surface any connectivity error to the caller
        checks["postgres"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        overall_ok = False

    try:
        r = redis.Redis.from_url(settings.redis_url(), socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        checks["redis"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        overall_ok = False

    return {"status": "ok" if overall_ok else "degraded", "checks": checks}
