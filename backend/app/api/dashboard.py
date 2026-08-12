from __future__ import annotations

from fastapi import APIRouter

from app.metrics import dashboard_cache
from app.schemas.dashboard import DashboardSummaryRead

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummaryRead)
def get_dashboard() -> DashboardSummaryRead:
    """Served from a short-lived background-refreshed cache, not computed
    fresh on every call - see app.metrics.dashboard_cache for why (a real
    computation over a real 1,400+-list collection takes ~14s). No `db`
    dependency here on purpose: the cache's own background refresh thread
    opens its own session (a request-scoped one from `get_db` would be
    closed by the time that thread runs).
    """
    return DashboardSummaryRead.model_validate(dashboard_cache.get_dashboard_summary_cached())
