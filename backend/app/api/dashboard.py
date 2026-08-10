from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.metrics import dashboard_service
from app.schemas.dashboard import DashboardSummaryRead

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummaryRead)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardSummaryRead:
    return DashboardSummaryRead.model_validate(dashboard_service.get_dashboard_summary(db))
