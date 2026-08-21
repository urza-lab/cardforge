"""Short-lived, background-refreshed cache for `dashboard_service.
get_dashboard_summary` (user-requested) - a real computation over a real
1,400+-list collection takes ~14s (see CLAUDE.md gotchas #32/#33), too
slow to recompute on every single page view of what's fundamentally a
"recent snapshot" dashboard, not a live-trading ticker.

Deliberately NOT a fixed background timer (unlike app.workers.run_worker's
periodic sync loop) - that would keep recomputing on a schedule even while
nobody's looking at the dashboard. Instead: the first request after the
cache goes stale triggers a background refresh (in a plain thread, same
shape as everything else in this project that needed one-off background
work without adding a task queue dependency) and gets served the
*previous* cached result immediately, with `is_refreshing`/
`refresh_eta_seconds` set so the frontend can show an honest "showing data
from Xs ago, refreshing now" disclaimer instead of silently serving stale
data or blocking the request - "no fake success" applies to staleness
too, not just wrong numbers.

The very first call ever (a fresh backend process with nothing cached yet)
has no previous result to fall back to, so it blocks for the one real
~14s computation - every request after that is served from cache almost
instantly, refreshing in the background as needed.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime

from app.core.database import get_sessionmaker
from app.metrics.dashboard_service import DashboardSummary, get_dashboard_summary
from app.models.user import DEFAULT_USER_ID

log = logging.getLogger("cardforge.dashboard_cache")

CACHE_TTL_SECONDS = 60

_lock = threading.Lock()
_cached: DashboardSummary | None = None
_cached_at: datetime | None = None
_refreshing = False
_refresh_started_at: datetime | None = None
_last_duration_seconds: float | None = None
# Set once the very first computation (successful or not) finishes - lets a
# second request that lands *while* that first blocking call is still
# running wait for the real result instead of assuming it's already there
# (see get_dashboard_summary_cached's own note on the real race this fixes).
_first_computed_event = threading.Event()


def _is_stale() -> bool:
    if _cached is None or _cached_at is None:
        return True
    return (datetime.now(UTC) - _cached_at).total_seconds() > CACHE_TTL_SECONDS


def _eta_seconds() -> float | None:
    if not _refreshing or _refresh_started_at is None or _last_duration_seconds is None:
        return None
    elapsed = (datetime.now(UTC) - _refresh_started_at).total_seconds()
    return max(_last_duration_seconds - elapsed, 0.0)


def _refresh(user_id: int) -> None:
    global _cached, _cached_at, _refreshing, _last_duration_seconds
    session_local = get_sessionmaker()
    db = session_local()
    t0 = time.time()
    try:
        summary = get_dashboard_summary(db, user_id=user_id)
    except Exception:
        # A caller blocked on the synchronous first-ever computation still
        # sees this exception directly (it propagates out of this call);
        # this log is for the *background*-thread case, where an exception
        # here would otherwise vanish silently (Python only prints an
        # unhandled-exception traceback for a daemon thread, nothing this
        # app's own logging/monitoring would ever see) - "no fake success"
        # applies to a refresh that silently never happens, too.
        log.exception("dashboard cache refresh failed")
        # Deliberately does NOT touch _cached - a failed refresh leaves
        # whatever was there before (or None) exactly as it was. Still has
        # to clear _refreshing and wake the event though, otherwise a
        # failure leaves the cache permanently stuck "refreshing forever"
        # (no future stale request would ever retry) and, on the very
        # first-ever call, leaves a second request waiting on
        # _first_computed_event hanging forever instead of getting the
        # same failure.
        with _lock:
            _refreshing = False
        _first_computed_event.set()
        raise
    finally:
        db.close()

    duration = time.time() - t0
    with _lock:
        _cached = summary
        _cached_at = datetime.now(UTC)
        _last_duration_seconds = duration
        _refreshing = False
    _first_computed_event.set()


def clear() -> None:
    """Resets all cache state - real production code never needs this (the
    TTL handles real staleness), but the test suite does: this module-level
    cache would otherwise leak a stale result across tests that reset the
    database between them (see tests/conftest.py's `_clean_db` fixture).
    """
    global _cached, _cached_at, _refreshing, _refresh_started_at, _last_duration_seconds
    with _lock:
        _cached = None
        _cached_at = None
        _refreshing = False
        _refresh_started_at = None
        _last_duration_seconds = None
    _first_computed_event.clear()


def get_dashboard_summary_cached(*, user_id: int = DEFAULT_USER_ID) -> DashboardSummary:
    global _refreshing, _refresh_started_at

    with _lock:
        stale = _is_stale()
        start_refresh_now = stale and not _refreshing
        if start_refresh_now:
            _refreshing = True
            _refresh_started_at = datetime.now(UTC)
        # A second request landing while someone else's first-ever
        # computation is still running (found live, 2026-08-20: this
        # computation used to take ~14s at ~1,400 lists, rarely enough for
        # a real second caller to land inside that window - a real
        # collection scaling into the tens of thousands of lists stretched
        # that window to minutes, and a concurrent request during it hit an
        # assertion here that assumed _cached was already populated by the
        # time any *other* caller reached this point).
        must_wait_for_first_ever = _cached is None and not start_refresh_now

    if start_refresh_now:
        if _cached is None:
            # Nothing to serve while refreshing - this is the one real
            # blocking computation a freshly started backend ever pays.
            _refresh(user_id)
        else:
            threading.Thread(target=_refresh, args=(user_id,), daemon=True).start()
    elif must_wait_for_first_ever:
        _first_computed_event.wait()

    with _lock:
        if _cached is None:
            # Only reachable if the very first-ever computation itself
            # failed (see _refresh's except branch) - a real, specific
            # error beats a bare AssertionError here, since a caller that
            # was only waiting on someone *else's* first computation has no
            # traceback of its own to show otherwise.
            raise RuntimeError("dashboard summary has never been computed successfully - check backend logs")
        return replace(
            _cached, computed_at=_cached_at, is_refreshing=_refreshing, refresh_eta_seconds=_eta_seconds()
        )
